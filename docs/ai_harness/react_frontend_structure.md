# React Frontend Structure

React/Vite/TypeScriptの新規UIを作る時の最小フォルダ設計です。
既存がNext.jsの場合はこの構造へ移行せず、責務分離だけを既存の `app/` 構成へ読み替えます。

## 推奨構成

```text
src/
├─ app/
│  ├─ App.tsx
│  ├─ main.tsx
│  └─ routes.tsx
├─ pages/
│  ├─ DashboardPage.tsx
│  └─ SettingsPage.tsx
├─ components/
│  ├─ ui/
│  │  ├─ Button.tsx
│  │  ├─ Card.tsx
│  │  └─ Input.tsx
│  └─ feature/
│     ├─ TradeSummaryCard.tsx
│     └─ RiskTable.tsx
├─ hooks/
│  └─ useTradeSummary.ts
├─ services/
│  └─ api.ts
├─ lib/
│  ├─ format.ts
│  └─ calc.ts
├─ types/
│  └─ trade.ts
├─ styles/
│  └─ globals.css
└─ test/
   ├─ setup.ts
   └─ utils.tsx
```

```text
tests/
├─ unit/
├─ component/
└─ e2e/
```

## 責務

- `pages/`: 画面単位。ページの構成とデータの受け渡しを担当する。
- `components/ui/`: Button、Card、Inputなどの汎用見た目部品。
- `components/feature/`: TradeSummaryCard、RiskTableなど業務意味を持つ部品。
- `hooks/`: 画面やfeatureが使う状態管理、データ取得の薄いラッパー。
- `services/`: fetch、API client、backend呼び出し。
- `lib/`: 損益、勝率、最大DD、formatなど副作用のない計算。
- `types/`: 複数ファイルで共有するTypeScript型。
- `styles/`: global CSSと共通theme token。

## AIハーネスでの指定例

- `components/feature/TradeSummaryCard.tsx` だけ修正する。
- `lib/calc.ts` に最大DD計算を追加し、`tests/unit/calc.test.ts` を更新する。
- `services/api.ts` にAPI関数を追加し、型は `types/trade.ts` に置く。
- `pages/DashboardPage.tsx` に既存feature componentを配置する。

## 避けること

- `components/` へ画面、通信、計算、型を全部入れる。
- `pages/` に損益計算やfetch詳細を直書きする。
- API型を各component内に散らす。
- 1行だけの部品やhooksを大量に作る。
- 依存追加やframework migrationを仕様なしで行う。
