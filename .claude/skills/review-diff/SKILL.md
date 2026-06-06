---
name: review-diff
description: Strictly review the current diff against the Ouroboros harness spec and review rubric.
disable-model-invocation: true
allowed-tools: Read Grep Glob Bash
---

# Review Diff

Review the current diff like a skeptical QA reviewer.

## Required reading

- `docs/ai_harness/current_spec.md`
- `docs/ai_harness/constraints.md`
- `docs/ai_harness/ouroboros_quality_gate.md`
- `docs/ai_harness/review_rubric.md`

## Review focus

- Bugs, behavior regressions, safety risks, missing tests.
- Spec drift and excessive changes.
- Trading safety and log/report/widget contract compatibility.
- Whether `./scripts/validate.sh fast` or `trade` is the right gate.
- Whether `python3 tools/harness_quality_check.py` should have been run before implementation.

## Output

Findings first, ordered by severity. If no findings, say that and list residual risks.
