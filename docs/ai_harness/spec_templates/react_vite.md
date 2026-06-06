# React Vite Spec Template

Status: READY

## Goal

- React + Vite + TypeScriptの画面または新規UIを、AIハーネスで管理しやすい最小構成で追加・変更する。

## Input

- 対象アプリ名またはfrontend root:
- 対象画面:
- 入力データ/API:
- 追加するUI:

## Output

- 追加または変更するpage:
- 追加または変更するcomponent:
- 追加または変更するlib/service/type:
- 追加または変更するtest:

## Constraints

- `docs/ai_harness/constraints.md` を必ず守る。
- `docs/ai_harness/react_frontend_structure.md` の責務分離を守る。
- 既存がNext.jsの場合は、Vite構成へ無理に移行しない。既存の `app/` 構造へ合わせる。
- 依存追加、UIライブラリ追加、framework migrationは明示承認なしで行わない。
- 1行だけの過剰な小コンポーネント分割や、過剰なhooks分離をしない。

## Pre-Implementation Contract

- Allowed Files: docs/**, .vscode/tasks.json, package.json, tsconfig.json, vite.config.ts, src/**, tests/**, public/**
- Runtime Impact: local-only
- Data Contract: 型は `src/types/`、API通信は `src/services/`、計算処理は `src/lib/` に置く。
- Safety Gate: UI-only
- Validation: fast
- Rollback: 追加したReact/Vite関連ファイルを戻し、既存画面差分は元のpage/component単位で戻す。

## Acceptance Criteria

- [ ] 画面単位は `src/pages/`、汎用部品は `src/components/ui/`、機能部品は `src/components/feature/` に分かれている。
- [ ] 計算処理はcomponent内へ直書きせず、`src/lib/` に分離している。
- [ ] API通信はcomponent内へ散らさず、`src/services/` に寄せている。
- [ ] TypeScriptの共有型は `src/types/` に置いている。
- [ ] 対象プロジェクトに存在する場合、`npm run lint` / `npm run typecheck` / `npm run test` / `npm run build` が成功する。
- [ ] Ouroboros repo内の変更なら `./scripts/validate.sh fast` が成功する。

## Out Of Scope

- Next.jsからViteへの移行。
- 有料APIや外部UIサービス前提の追加。
- VM deploy。
- trading main実弾挙動の変更。
