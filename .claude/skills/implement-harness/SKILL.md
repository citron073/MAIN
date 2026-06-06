---
name: implement-harness
description: Implement one READY feature using the local Ouroboros harness, then run validation. Invoke manually when starting a bounded code change from docs/ai_harness/current_spec.md.
disable-model-invocation: true
---

# Implement Harness

Implement only the feature described in `docs/ai_harness/current_spec.md`.

## Required reading

- `docs/ai_harness/current_spec.md`
- `docs/ai_harness/constraints.md`
- `docs/ai_harness/ouroboros_quality_gate.md`
- `docs/ai_harness/definition-of-done.md`
- `docs/ai_harness/review_rubric.md`

## Stop conditions

- If `current_spec.md` is not `Status: READY`, stop and ask for the spec to be marked READY.
- If the requested change needs secrets, production control changes, dependency installs, or VM deploy, stop and ask before doing that part.

## Work loop

1. Restate the bounded change and allowed files.
2. Identify the applicable gate: trading/shadow, widget/UI, LLM/reflection, or docs-only.
3. Run `python3 tools/harness_quality_check.py` before editing.
4. Edit only the minimum files needed.
5. Add or update tests when the behavior is contract-like.
6. Run `./scripts/validate.sh fast`.
7. If trading, widget, notifier, reflection, or MR observe changed, run `./scripts/validate.sh trade`.
8. If validation fails, run `./scripts/extract_failures.sh`, summarize `.harness/failures.txt`, and make the smallest fix.
9. Report changed files, validation result, applicable gate, and remaining risk.
