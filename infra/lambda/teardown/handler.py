"""Harbormaster nightly teardown Lambda.

This function is a FinOps guardrail for the Harbormaster maritime
anomaly-detection platform (a personal project by Arun Sharma). It runs on a
nightly EventBridge schedule and tears down or quiesces the cost-heavy,
tag-scoped resources that are easy to leave running by accident: Managed
Service for Apache Flink applications, EMR clusters, MSK Serverless clusters,
Auto Scaling Groups, Harbormaster EKS Network Load Balancers, NAT gateways, and
unattached Elastic IPs. It then reports month-to-date spend to an SNS topic.

Design principles:
  - Defensive per service: a failure in one service must never abort the run.
    Every service block is wrapped in its own try/except, and exceptions are
    logged and accumulated, not raised.
  - Tag-scoped: every resource must match Project=<PROJECT_TAG>. W4 network
    resources must also match Environment=<ENVIRONMENT> and their owning
    Module tag before a destructive API request is issued.
  - DRY_RUN by default: with DRY_RUN unset or "true", the function logs the
    actions it WOULD take and changes nothing. Set DRY_RUN=false to act.
  - No third-party dependencies: boto3 only, which is present in the Lambda
    Python runtime. requirements.txt exists for local testing convenience.

Environment variables:
  DRY_RUN          "true" (default) logs intended actions; "false" performs them.
  ALERT_TOPIC_ARN  SNS topic ARN that receives the spend summary. Optional; if
                   unset, the summary is logged only.
  PROJECT_TAG      Tag value that scopes every action. Default "harbormaster".
  ENVIRONMENT      Environment tag required for W4 network cleanup. Default
                   "base".
  AWS_REGION       Provided by the Lambda runtime; used implicitly by boto3.
"""

import datetime
import json
import logging
import os

try:
    import boto3
except ImportError:  # pragma: no cover
    # boto3 is always present in the Lambda runtime. Off-cloud (for example a
    # bare CI box running the tests) it may be absent. We keep the name defined
    # so tests can monkeypatch handler.boto3.client; the real cloud path always
    # has the SDK.
    boto3 = None

# Structured logging. We emit JSON-ish records via the standard logger so the
# output is greppable in CloudWatch Logs without a logging dependency.
logger = logging.getLogger()
if logger.handlers:
    # Lambda pre-configures a handler; just set the level.
    logger.setLevel(logging.INFO)
else:
    logging.basicConfig(level=logging.INFO)


def _env_bool(name, default):
    """Parse a boolean-ish environment variable. Anything other than an
    explicit false-y string ("false", "0", "no", "off") is treated as True so
    that the safe DRY_RUN default is preserved on typos."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off")


def _log(event_name, **fields):
    """Emit one structured log line. Keeps a consistent shape so downstream
    log queries can filter on the "event" key."""
    record = {"event": event_name}
    record.update(fields)
    logger.info(json.dumps(record, default=str))


PROJECT_TAG_VALUE = os.environ.get("PROJECT_TAG", "harbormaster")
ENVIRONMENT_VALUE = os.environ.get("ENVIRONMENT", "base")


def _tag_matches(tags, key="Project", value=None):
    """Return True if the supplied tag collection contains key=value.

    Accepts both the list-of-dicts shape ([{"Key":..,"Value":..}]) used by EMR,
    ASG, and Kinesis Analytics, and the flat dict shape ({"Project": ...}) used
    by some MSK/tagging APIs."""
    value = value if value is not None else PROJECT_TAG_VALUE
    if not tags:
        return False
    if isinstance(tags, dict):
        return tags.get(key) == value
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        # Kinesis Analytics and EMR use Key/Value; some APIs use lowercase.
        k = tag.get("Key", tag.get("key"))
        v = tag.get("Value", tag.get("value"))
        if k == key and v == value:
            return True
    return False


def _network_scope_matches(tags, module):
    """Require the exact Terraform ownership tags for a W4 network resource."""
    return (
        _tag_matches(tags)
        and _tag_matches(tags, key="Environment", value=ENVIRONMENT_VALUE)
        and _tag_matches(tags, key="Module", value=module)
    )


# --------------------------------------------------------------------------- #
# Managed Service for Apache Flink (kinesisanalyticsv2)
# --------------------------------------------------------------------------- #
def stop_flink_applications(dry_run, results):
    """Stop any RUNNING Managed Service for Apache Flink applications that are
    tagged for this project."""
    service = "managed_flink"
    stopped = []
    try:
        client = boto3.client("kinesisanalyticsv2")
        paginator_marker = None
        apps = []
        while True:
            kwargs = {"Limit": 50}
            if paginator_marker:
                kwargs["NextToken"] = paginator_marker
            resp = client.list_applications(**kwargs)
            apps.extend(resp.get("ApplicationSummaries", []))
            paginator_marker = resp.get("NextToken")
            if not paginator_marker:
                break

        for app in apps:
            name = app.get("ApplicationName")
            status = app.get("ApplicationStatus")
            arn = app.get("ApplicationARN")
            try:
                tag_resp = client.list_tags_for_resource(ResourceARN=arn)
                tags = tag_resp.get("Tags", [])
            except Exception as tag_err:  # noqa: BLE001
                _log("flink_tag_lookup_failed", application=name, error=str(tag_err))
                continue

            if not _tag_matches(tags):
                continue
            if status != "RUNNING":
                _log("flink_skip_not_running", application=name, status=status)
                continue

            if dry_run:
                _log("flink_would_stop", application=name, status=status)
                stopped.append(name)
                continue

            client.stop_application(ApplicationName=name, Force=True)
            _log("flink_stopped", application=name)
            stopped.append(name)

        results[service] = {"stopped": stopped, "error": None}
    except Exception as err:  # noqa: BLE001
        _log("flink_block_failed", error=str(err))
        results[service] = {"stopped": stopped, "error": str(err)}
    return results


# --------------------------------------------------------------------------- #
# EMR
# --------------------------------------------------------------------------- #
def terminate_emr_clusters(dry_run, results):
    """Terminate orphaned EMR clusters tagged for this project that are in an
    active (non-terminating, non-terminated) state."""
    service = "emr"
    terminated = []
    active_states = ["STARTING", "BOOTSTRAPPING", "RUNNING", "WAITING"]
    try:
        client = boto3.client("emr")
        marker = None
        cluster_ids = []
        while True:
            kwargs = {"ClusterStates": active_states}
            if marker:
                kwargs["Marker"] = marker
            resp = client.list_clusters(**kwargs)
            for c in resp.get("Clusters", []):
                cluster_ids.append((c.get("Id"), c.get("Name")))
            marker = resp.get("Marker")
            if not marker:
                break

        to_terminate = []
        for cid, cname in cluster_ids:
            try:
                desc = client.describe_cluster(ClusterId=cid)
                tags = desc.get("Cluster", {}).get("Tags", [])
            except Exception as desc_err:  # noqa: BLE001
                _log("emr_describe_failed", cluster_id=cid, error=str(desc_err))
                continue
            if not _tag_matches(tags):
                continue
            to_terminate.append((cid, cname))

        for cid, cname in to_terminate:
            if dry_run:
                _log("emr_would_terminate", cluster_id=cid, cluster_name=cname)
                terminated.append(cid)
                continue
            client.terminate_job_flows(JobFlowIds=[cid])
            _log("emr_terminated", cluster_id=cid, cluster_name=cname)
            terminated.append(cid)

        results[service] = {"terminated": terminated, "error": None}
    except Exception as err:  # noqa: BLE001
        _log("emr_block_failed", error=str(err))
        results[service] = {"terminated": terminated, "error": str(err)}
    return results


# --------------------------------------------------------------------------- #
# MSK Serverless
# --------------------------------------------------------------------------- #
def delete_msk_serverless_clusters(dry_run, results):
    """Delete MSK Serverless clusters tagged for this project. MSK has no
    "stop"; the serverless variant bills for storage and partitions while it
    exists, so teardown is a delete."""
    service = "msk_serverless"
    deleted = []
    try:
        client = boto3.client("kafka")
        token = None
        clusters = []
        while True:
            kwargs = {"ClusterTypeFilter": "SERVERLESS", "MaxResults": 50}
            if token:
                kwargs["NextToken"] = token
            try:
                resp = client.list_clusters_v2(**kwargs)
            except TypeError:
                # Older botocore without ClusterTypeFilter support: fall back.
                resp = client.list_clusters_v2(MaxResults=50)
            clusters.extend(resp.get("ClusterInfoList", []))
            token = resp.get("NextToken")
            if not token:
                break

        for cluster in clusters:
            arn = cluster.get("ClusterArn")
            name = cluster.get("ClusterName")
            cluster_type = cluster.get("ClusterType")
            if cluster_type and cluster_type != "SERVERLESS":
                continue
            tags = cluster.get("Tags", {})
            if not tags:
                try:
                    tags = client.list_tags_for_resource(ResourceArn=arn).get("Tags", {})
                except Exception as tag_err:  # noqa: BLE001
                    _log("msk_tag_lookup_failed", cluster=name, error=str(tag_err))
                    continue
            if not _tag_matches(tags):
                continue

            if dry_run:
                _log("msk_would_delete", cluster=name, arn=arn)
                deleted.append(name)
                continue
            client.delete_cluster(ClusterArn=arn)
            _log("msk_deleted", cluster=name, arn=arn)
            deleted.append(name)

        results[service] = {"deleted": deleted, "error": None}
    except Exception as err:  # noqa: BLE001
        _log("msk_block_failed", error=str(err))
        results[service] = {"deleted": deleted, "error": str(err)}
    return results


# --------------------------------------------------------------------------- #
# Auto Scaling Groups
# --------------------------------------------------------------------------- #
def zero_auto_scaling_groups(dry_run, results):
    """Set the desired capacity of any tagged Auto Scaling Group to 0. We do
    not delete the ASG so its definition survives for the next demo bring-up;
    we just drain the instances that cost money."""
    service = "auto_scaling"
    zeroed = []
    try:
        client = boto3.client("autoscaling")
        paginator = client.get_paginator("describe_auto_scaling_groups")
        for page in paginator.paginate():
            for asg in page.get("AutoScalingGroups", []):
                name = asg.get("AutoScalingGroupName")
                tags = asg.get("Tags", [])
                if not _tag_matches(tags):
                    continue
                desired = asg.get("DesiredCapacity", 0)
                if desired == 0 and asg.get("MinSize", 0) == 0:
                    _log("asg_already_zero", asg=name)
                    continue
                if dry_run:
                    _log("asg_would_zero", asg=name, current_desired=desired)
                    zeroed.append(name)
                    continue
                client.update_auto_scaling_group(
                    AutoScalingGroupName=name,
                    MinSize=0,
                    DesiredCapacity=0,
                )
                _log("asg_zeroed", asg=name, previous_desired=desired)
                zeroed.append(name)

        results[service] = {"zeroed": zeroed, "error": None}
    except Exception as err:  # noqa: BLE001
        _log("asg_block_failed", error=str(err))
        results[service] = {"zeroed": zeroed, "error": str(err)}
    return results


# --------------------------------------------------------------------------- #
# EKS front-door Network Load Balancers
# --------------------------------------------------------------------------- #
def delete_network_load_balancers(dry_run, results):
    """Delete only project-tagged NLBs owned by the EKS front-door module."""
    service = "network_load_balancers"
    would_delete = []
    delete_requested = []
    try:
        client = boto3.client("elbv2")
        paginator = client.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for load_balancer in page.get("LoadBalancers", []):
                if load_balancer.get("Type") != "network":
                    continue
                arn = load_balancer.get("LoadBalancerArn")
                name = load_balancer.get("LoadBalancerName")
                try:
                    descriptions = client.describe_tags(ResourceArns=[arn]).get(
                        "TagDescriptions", []
                    )
                    tags = descriptions[0].get("Tags", []) if descriptions else []
                except Exception as tag_err:  # noqa: BLE001
                    _log("nlb_tag_lookup_failed", load_balancer=name, error=str(tag_err))
                    continue
                if not _network_scope_matches(tags, module="eks_frontdoor"):
                    continue
                if dry_run:
                    _log("nlb_would_delete", load_balancer=name, arn=arn)
                    would_delete.append(name)
                    continue
                client.delete_load_balancer(LoadBalancerArn=arn)
                _log("nlb_delete_requested", load_balancer=name, arn=arn)
                delete_requested.append(name)

        results[service] = {
            "would_delete": would_delete,
            "delete_requested": delete_requested,
            "error": None,
        }
    except Exception as err:  # noqa: BLE001
        _log("nlb_block_failed", error=str(err))
        results[service] = {
            "would_delete": would_delete,
            "delete_requested": delete_requested,
            "error": str(err),
        }
    return results


# --------------------------------------------------------------------------- #
# NAT gateways
# --------------------------------------------------------------------------- #
def delete_nat_gateways(dry_run, results):
    """Request deletion of active NAT gateways with exact ownership tags."""
    service = "nat_gateways"
    would_delete = []
    delete_requested = []
    try:
        client = boto3.client("ec2")
        gateways = []
        token = None
        while True:
            kwargs = {"Filter": [{"Name": "tag:Project", "Values": [PROJECT_TAG_VALUE]}]}
            if token:
                kwargs["NextToken"] = token
            response = client.describe_nat_gateways(**kwargs)
            gateways.extend(response.get("NatGateways", []))
            token = response.get("NextToken")
            if not token:
                break
        for gateway in gateways:
            gateway_id = gateway.get("NatGatewayId")
            state = gateway.get("State")
            if not _network_scope_matches(gateway.get("Tags", []), module="network"):
                continue
            if state not in {"available", "pending"}:
                _log("nat_gateway_skip_state", nat_gateway_id=gateway_id, state=state)
                continue
            if dry_run:
                _log("nat_gateway_would_delete", nat_gateway_id=gateway_id, state=state)
                would_delete.append(gateway_id)
                continue
            client.delete_nat_gateway(NatGatewayId=gateway_id)
            _log("nat_gateway_delete_requested", nat_gateway_id=gateway_id, prior_state=state)
            delete_requested.append(gateway_id)

        results[service] = {
            "would_delete": would_delete,
            "delete_requested": delete_requested,
            "error": None,
        }
    except Exception as err:  # noqa: BLE001
        _log("nat_gateway_block_failed", error=str(err))
        results[service] = {
            "would_delete": would_delete,
            "delete_requested": delete_requested,
            "error": str(err),
        }
    return results


# --------------------------------------------------------------------------- #
# Unattached Elastic IPs
# --------------------------------------------------------------------------- #
def release_unattached_elastic_ips(dry_run, results):
    """Release project-tagged VPC Elastic IPs after they are unattached."""
    service = "elastic_ips"
    would_release = []
    release_requested = []
    try:
        client = boto3.client("ec2")
        response = client.describe_addresses(
            Filters=[{"Name": "tag:Project", "Values": [PROJECT_TAG_VALUE]}]
        )
        addresses = response.get("Addresses", [])
        for address in addresses:
            allocation_id = address.get("AllocationId")
            if not allocation_id or not _network_scope_matches(
                address.get("Tags", []), module="network"
            ):
                continue
            attachment_fields = (
                "AssociationId",
                "NetworkInterfaceId",
                "InstanceId",
                "PrivateIpAddress",
            )
            if any(address.get(field) for field in attachment_fields):
                _log("elastic_ip_skip_attached", allocation_id=allocation_id)
                continue
            if dry_run:
                _log("elastic_ip_would_release", allocation_id=allocation_id)
                would_release.append(allocation_id)
                continue
            client.release_address(AllocationId=allocation_id)
            _log("elastic_ip_release_requested", allocation_id=allocation_id)
            release_requested.append(allocation_id)

        results[service] = {
            "would_release": would_release,
            "release_requested": release_requested,
            "error": None,
        }
    except Exception as err:  # noqa: BLE001
        _log("elastic_ip_block_failed", error=str(err))
        results[service] = {
            "would_release": would_release,
            "release_requested": release_requested,
            "error": str(err),
        }
    return results


# --------------------------------------------------------------------------- #
# Cost Explorer month-to-date spend
# --------------------------------------------------------------------------- #
def get_month_to_date_spend(results):
    """Query Cost Explorer for unblended month-to-date spend. Cost Explorer is
    only available in us-east-1, so we pin the client region explicitly."""
    service = "cost_explorer"
    summary = {"amount": None, "unit": None, "start": None, "end": None}
    try:
        today = datetime.date.today()
        start = today.replace(day=1)
        # Cost Explorer End is exclusive; use tomorrow so today is included.
        end = today + datetime.timedelta(days=1)
        client = boto3.client("ce", region_name="us-east-1")
        resp = client.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )
        by_time = resp.get("ResultsByTime", [])
        total = 0.0
        unit = "USD"
        for window in by_time:
            metric = window.get("Total", {}).get("UnblendedCost", {})
            total += float(metric.get("Amount", "0") or "0")
            unit = metric.get("Unit", unit)
        summary = {
            "amount": round(total, 2),
            "unit": unit,
            "start": start.isoformat(),
            "end": today.isoformat(),
        }
        _log("cost_explorer_mtd", **summary)
        results[service] = {"summary": summary, "error": None}
    except Exception as err:  # noqa: BLE001
        _log("cost_explorer_failed", error=str(err))
        results[service] = {"summary": summary, "error": str(err)}
    return results


# --------------------------------------------------------------------------- #
# SNS publish
# --------------------------------------------------------------------------- #
def publish_summary(dry_run, results):
    """Publish a human-readable teardown summary to the SNS topic named in
    ALERT_TOPIC_ARN. If the topic is unset, the summary is logged only."""
    topic_arn = os.environ.get("ALERT_TOPIC_ARN")
    cost = results.get("cost_explorer", {}).get("summary", {})
    lines = [
        "Harbormaster nightly teardown summary",
        "DRY_RUN: {}".format("yes" if dry_run else "no"),
        f"Project tag: {PROJECT_TAG_VALUE}",
    ]
    flink = results.get("managed_flink", {})
    emr = results.get("emr", {})
    msk = results.get("msk_serverless", {})
    asg = results.get("auto_scaling", {})
    nlb = results.get("network_load_balancers", {})
    nat = results.get("nat_gateways", {})
    eip = results.get("elastic_ips", {})
    lines.append("Flink apps stopped: {}".format(flink.get("stopped", [])))
    lines.append("EMR clusters terminated: {}".format(emr.get("terminated", [])))
    lines.append("MSK serverless deleted: {}".format(msk.get("deleted", [])))
    lines.append("ASGs set to 0: {}".format(asg.get("zeroed", [])))
    lines.append("EKS front-door NLB delete requests: {}".format(nlb.get("delete_requested", [])))
    lines.append("EKS front-door NLB dry-run targets: {}".format(nlb.get("would_delete", [])))
    lines.append("NAT gateway delete requests: {}".format(nat.get("delete_requested", [])))
    lines.append("NAT gateway dry-run targets: {}".format(nat.get("would_delete", [])))
    lines.append("Elastic IP release requests: {}".format(eip.get("release_requested", [])))
    lines.append("Elastic IP dry-run targets: {}".format(eip.get("would_release", [])))
    if cost.get("amount") is not None:
        lines.append(
            "Month-to-date spend: {} {} (through {})".format(
                cost.get("amount"), cost.get("unit"), cost.get("end")
            )
        )
    else:
        lines.append("Month-to-date spend: unavailable")

    # Surface any per-service errors so a partial failure is visible in alerts.
    errors = {
        svc: payload.get("error")
        for svc, payload in results.items()
        if isinstance(payload, dict) and payload.get("error")
    }
    if errors:
        lines.append(f"Errors: {json.dumps(errors, default=str)}")

    message = "\n".join(lines)

    if not topic_arn:
        _log("sns_skip_no_topic", message=message)
        results["sns"] = {"published": False, "error": None}
        return results

    if dry_run:
        _log("sns_would_publish", topic_arn=topic_arn, message=message)
        results["sns"] = {"published": False, "error": None}
        return results

    try:
        sns = boto3.client("sns")
        sns.publish(
            TopicArn=topic_arn,
            Subject="Harbormaster nightly teardown",
            Message=message,
        )
        _log("sns_published", topic_arn=topic_arn)
        results["sns"] = {"published": True, "error": None}
    except Exception as err:  # noqa: BLE001
        _log("sns_publish_failed", error=str(err))
        results["sns"] = {"published": False, "error": str(err)}
    return results


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def lambda_handler(event, context):
    """EventBridge entry point. Runs each teardown step defensively, then
    reports spend. Returns a JSON-serializable dict describing what happened so
    the result is visible in the Lambda console and in step logs."""
    dry_run = _env_bool("DRY_RUN", True)
    _log(
        "teardown_start",
        dry_run=dry_run,
        project_tag=PROJECT_TAG_VALUE,
        environment=ENVIRONMENT_VALUE,
        event=event if isinstance(event, dict) else str(event),
    )

    results = {}
    # Each step is independent and catches its own exceptions, so the order is
    # only about reporting clarity, not correctness.
    stop_flink_applications(dry_run, results)
    terminate_emr_clusters(dry_run, results)
    delete_msk_serverless_clusters(dry_run, results)
    zero_auto_scaling_groups(dry_run, results)
    delete_network_load_balancers(dry_run, results)
    delete_nat_gateways(dry_run, results)
    release_unattached_elastic_ips(dry_run, results)
    get_month_to_date_spend(results)
    publish_summary(dry_run, results)

    _log("teardown_complete", dry_run=dry_run)
    return {
        "dry_run": dry_run,
        "project_tag": PROJECT_TAG_VALUE,
        "environment": ENVIRONMENT_VALUE,
        "results": results,
    }


if __name__ == "__main__":
    # Local smoke run. With no AWS credentials the boto3 calls will fail, but
    # each service block catches its own error, so this still exits cleanly and
    # prints the accumulated result. Set DRY_RUN=true (the default) to be safe.
    print(json.dumps(lambda_handler({"source": "local"}, None), indent=2, default=str))
