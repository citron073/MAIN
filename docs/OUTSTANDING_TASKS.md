# 残タスク台帳（未実施・保留・観測待ち）

> 2026-06-14 作成。トレード全体(swing/IBKR/BTC/インフラ/新フィールド)の横断バックログ。
> 凡例: 🟢自走可 / 🟡たにさん承認要(領域1等) / ⏳観測・データ待ち / ❄️凍結 / ✅完了

---

## A. swingbot（本線）— Phase進行
| 項目 | 状態 | 次アクション |
|------|------|------------|
| Phase A PAPER 9市場稼働 | ✅ | 毎日09:15判定中 |
| Phase B 実績照合(reconcile) | ⏳ | GREEN待ち(4-8週・初回はINSUFFICIENT) |
| 口座DD kill-switch | 🟡未実装 | **Phase C(実弾層)要件**: 口座DD-10%で新規停止→新高値まで休止 |
| MOO/MOC実約定記録 | 🟡未実装 | Phase C: PAPERは引け値近似で継続 |
| ベンチマーク(QQQ)対比をゲートに組込 | 🟡未実装 | 検証16: US株能動はバイ&ホールドQQQにリスク調整後で勝てて初めて正当 |
| account-equityベースのreconcile | 🟡未実装 | 現状sum-of-trades%。実弾化時に口座複利ベースへ |

## B. IBKR 5分bot — observe→block 昇格待ち
| 機能 | 状態 | 次アクション |
|------|------|------------|
| P2a ATR下限フィルタ | ✅block化済(6/12) | — |
| P2b トレンド整合 | ⏳observe | **block化の最優先候補**(ライブ発火が貯まり次第) |
| A SELL対称ガード | ⏳observe | データ蓄積後にblock化判断 |
| ドンチャン observe | ⏳observe | SMA一致率・約定品質を観測→採用判断 |
| C 通知(high+ログ) | ✅稼働 | — |
| B ATR-SL(sl2.0/tp4.0) | ✅有効 | ライブ実績の観測 |

## C. BTC 5分bot（LIVE実弾・現状維持R&D）
| 機能 | 状態 | 次アクション |
|------|------|------------|
| ATR-SL(atr_sl_multiplier=2.0) | ⏳Shadow検証中 | Shadow優位が出たらLIVE適用を🟡別途承認 |
| chop回避フィルタ | ⏳observe | 発火件数を週次レビュー(日曜19:00)で確認→block化 |

## D. 新フィールド候補（未着手）
| 項目 | 状態 | メモ |
|------|------|------|
| **日本株スイングWF審査** | ✅研究完了(検証17) | yfinanceで20銘柄審査→4合格(東エレク/アドテスト/OLC/三菱商事)。**OLC・三菱商事は米国クラスタと相関≈0=真の分散源**(検証15の天井突破)。次: PAPERへ組込 or 実弾執行のWindows/kabu問題 or Linux対応JP証券調査 |
| **配当グロース袖(Ricky型)** | 🟢可能(研究) | 日本増配株を never-sell。握力問題を「価格でなく配当を見る」で解決。要ファンダデータ(J-Quants)。**資金が育ったら起動する第2エンジン**(年800万配当≒元本2億級・即効性なし) |
| crypto実弾=現物ロングのみ | 🟡 | Phase C・決裁済(funding回避) |

## E. 運用・インフラ
| 項目 | 状態 | 担当 |
|------|------|------|
| 2FA犯人検証(別端末ログイン回避) | ⏳実施中 | **6/20に切断有無を確認**(たにさん) |
| GitHubデフォルトブランチ→main | 🟡未 | Web手動(たにさん) |
| critic類のexit-code誤警報 de-noise | 任意・見送り | SERVICE_HEALTH_TRIAGE.md 参照 |
| smokeテストを市場時間限定に | 任意・見送り | 場外failureノイズ |
| pyenv rehash警告 | 無害 | Mac側shimロック・VM無影響 |

## F. 観測待ち（自動・人手不要）
- 毎週日曜: BTC critic(20:00)/IBKR critic(20:30)/swing reconcile(21:00)
- 毎日: swing 9市場判定(09:15)・LLM通知(prebrief 20:50/review 07:05)

## ❄️ 凍結
- RAKUTEN 自動売買(Windows必須)
