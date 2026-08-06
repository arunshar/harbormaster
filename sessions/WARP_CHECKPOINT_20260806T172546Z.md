# WARP_CHECKPOINT_20260806T172546Z

Work unit: 20260806T171801Z
Owner UUID: fef81018-5f60-4285-8ab0-31430e3733e6
Created UTC: 2026-08-06T17:25:46Z
HEAD: 9f585908082a8c6e705571ed7f7d546de1563eb5
Result directory: /Users/arunsharma/code/harbormaster/artifacts/w4/20260806T171801Z-warp-project-remainder
Phase-evidence manifest SHA256: 568211eef455c3c54905e0cccdc428672b276fe0ccc25193231f00985d2341f2

## Predecessor
- sessions/WARP_CHECKPOINT_20260806T170832Z.md SHA256 cc955209d925fa37e048bd451b9e703ec6f0f94e6bccb710dd5cdd871e7d1677

## Stage classification
CANDIDATE_PLAN_READY_FOR_HUMAN_GATE

## Authorization consumed
AUTHORIZE_REVIEWS_AND_OUTER_MANIFEST

## Independent reviews
- Review 1 helper/publication/cleanup: GREEN
- Review 2 posture/state/CIDR/IAM/budget/guard: GREEN
- Review 3 e2e/command-boundary/operator readiness: GREEN
- Review 3 terraform-apply hit adjudicated FALSE_POSITIVE_DOCUMENTATION_DENIAL
  (printf denial strings only; no executable terraform apply)

## Outer manifest seal
- Path: artifacts/w4/20260806T160110Z-stage1-plan-recovery12/operator-plan-inputs.sha256
- SHA256: cfae7ee98193e4883a09d0db3520fe7d7caad802596b203c59598c30dc733d71
- Entries: 17
- Lists itself: no
- shasum -c: OK
- Core sealed input bytes unchanged through seal and post-seal suite

## Post-seal local suite
- candidate validator tests: 16/16 OK
- exact validator self-tests: OK
- bash -n helper/harness: OK
- ShellCheck warning: OK (pre-seal and identities unchanged)

## Package identities (unchanged)
- Helper: f6c6b4d19df1394dc1ed895e25c687edfc3c160fba36b4a195646890447ba515
- Harness: 18f7cc8cbaa983bd236695d0a10a7cc63f15c25c7701df310e547487d46da9eb
- Pins: adc986ea483a1f71282b8da0dcd608f9a8c40d6388f4535d7aa1d72821d9f83a
- Authorities: bc0d86232fd7cca6d16c52fb41f9fe54e4383e6e380cc83d16774ff10b02e753
- Contract: 3ccf7ed44c2139fa5f5400466055874fbedac52c783af59bc873c1b0312c293b

## Explicit non-authority
- Candidate-plan helper has NOT been run
- No Terraform plan/apply has been run
- Apply is not authorized
- Recovery11 remains expired evidence only

## Next human gate
HUMAN GATE REQUIRED: CANDIDATE PLAN
Present one checksum-bound command only after verifying helper mode, outer-manifest SHA, cutoff margin, and Git/package identities. No apply authorized by candidate capture.
