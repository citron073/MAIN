---
name: fix-failed-tests
description: Fix the smallest cause of the latest harness validation failure using .harness/failures.txt.
disable-model-invocation: true
---

# Fix Failed Tests

Use this only after `./scripts/validate.sh ...` failed.

## Required reading

- `.harness/failures.txt`
- `.harness/last_validate.log`
- `docs/ai_harness/constraints.md`
- `docs/ai_harness/ouroboros_quality_gate.md`
- `docs/ai_harness/current_spec.md`

## Rules

- Fix the smallest root cause.
- Do not broaden scope.
- Do not delete or weaken tests unless the spec explicitly changed.
- Re-run the same validation mode that failed.
- If the same failure remains after one fix attempt, stop and explain the blocker.
