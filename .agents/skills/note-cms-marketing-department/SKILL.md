---
name: note-cms-marketing-department
description: One-person marketing department orchestration for note CMS. Use when converting research seeds into note/X outputs, maintaining atoms/pipeline/outputs CSVs, or coordinating marketing skills through MAIN.
disable-model-invocation: true
---

# Note CMS Marketing Department

Use this skill when the task touches the "1人マーケ部門" workflow described in the reference PDF.

## Required Reading

- `docs/NOTE_CMS_MARKETING_DEPARTMENT.md`
- `docs/NOTE_CMS_OPERATION_MANUAL.md`
- `COMMANDS.md`
- `HANDOVER.md`
- `docs/ai_harness/current_spec.md`

## Shared Data Layer

- Seeds: `../note_cms_data/marketing/atoms.csv`
- Plans: `../note_cms_data/marketing/pipeline.csv`
- Published outputs: `../note_cms_data/marketing/outputs.csv`
- Import history: `../note_cms_data/marketing/import_history.json`
- Retry imports from Web UI `Marketing` > `Import History` with `失敗だけ再実行` or `重複以外を再実行`
- Use Web UI `Write` for the simplified writing flow: paste final text, preview links, auto-assist, check, copy
- Use Web UI `Articles` > `リンク候補プレビュー` / `自動整備` to extract note URLs, preview exact/related past-article links, and append safe internal-link CTAs

Initialize or export context:

```bash
python3 tools/note_cms_marketing_department.py --init
python3 tools/note_cms_marketing_department.py --stdout
```

The Web UI has a `Marketing` view for previewing imports, importing URL/PDF/text sources, bulk importing URL lists and PDF folders, skipping duplicate sources, writing import history, creating atoms, turning an atom into a note article, registering published outputs, and reviewing the latest 7 days.

## Workflow

1. Add content seeds to `atoms.csv`.
2. Decide channel expansion in `pipeline.csv`.
3. Produce note/X/visual assets through the relevant note CMS skill.
4. Run fact/design checks before publication.
5. Record published URLs and metrics in `outputs.csv`.
6. Feed results back into the next atom suggestion.

## Guard Rails

- Keep `note_cms_data/marketing/*.csv` as the shared data layer.
- Do not automate note publication.
- Do not add paid APIs or secret-bearing automation without explicit approval.
- Prefer one stable skill at a time; do not attempt to build all 21 skills in one step.
