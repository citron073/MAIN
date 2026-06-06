---
name: note-cms-orchestrator
description: Central entry point for the local note CMS. Use when you need to inspect ownership, launch the web UI, sync saved Google Sheets data, export orchestration context, or guide note article operations from MAIN.
disable-model-invocation: true
---

# Note CMS Orchestrator

Use this skill when the task touches the local `note_cms` workflow from `MAIN`.

## Required reading

- `docs/ai_harness/current_spec.md`
- `docs/ai_harness/constraints.md`
- `AGENTS.md`
- `HANDOVER.md`
- `COMMANDS.md`

## Entry points

- Web UI: `./tools/run_note_cms_web.sh`
- Saved Google sync: `./tools/sync_note_cms_saved_google.sh`
- Central context export: `python3 tools/note_cms_central_skill.py --stdout`

## Role map

- `note-cms-operator`: launch, backup, restore, routing
- `note-cms-editor`: draft, template, final body, X copy
- `note-cms-reviewer`: consistency check, signoff, release readiness
- `note-cms-sync-manager`: Google Sheets sync and periodic automation

## Guard rails

- Keep `note_cms/` as the source of truth. Do not move business logic into `MAIN/tools`.
- Treat note publication as manual.
- Do not add paid dependencies, VM deploy steps, or secret-bearing automation.
- When changing commands or handover behavior, update `COMMANDS.md` and `HANDOVER.*` together.
