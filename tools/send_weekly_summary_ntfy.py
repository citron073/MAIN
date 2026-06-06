#!/usr/bin/env python3
"""Send weekly AI auto-feedback summary to ntfy.

Called by ouroboros-weekly-autotrain.service as ExecStartPost.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
STATE_JSON = ROOT / "state.json"
SECRETS_TOML = ROOT / ".streamlit" / "secrets.toml"
LOGS_DIR = ROOT.parent / "logs"
BOT_PY = ROOT / "bot.py"
NOTIFY_STATE = ROOT / ".streamlit" / "notification_policy_state.json"

try:
    from tools.notification_policy import LEVEL_INFO, post_ntfy, read_toml_str
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT))
    from tools.notification_policy import LEVEL_INFO, post_ntfy, read_toml_str  # type: ignore


def _read_bot_version() -> str:
    try:
        from ouroboros_contract import OUROBOROS_BOT_VERSION

        return str(OUROBOROS_BOT_VERSION)
    except Exception:
        try:
            for line in BOT_PY.read_text(encoding="utf-8").splitlines()[:60]:
                if line.startswith("OUROBOROS_BOT_VERSION"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'").split("#")[0].strip()
        except Exception:
            pass
    return ""

def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _week_dates() -> Tuple[str, str]:
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday() + 7)
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y%m%d"), sunday.strftime("%Y%m%d")


def _build_ai_perf_line(lookback_weeks: int = 4) -> Optional[str]:
    ai_log = LOGS_DIR / "ai_training_log.csv"
    if not ai_log.exists():
        return None
    cutoff = (datetime.now() - timedelta(weeks=lookback_weeks)).date()
    win_sum = loss_sum = 0.0
    win_n = loss_n = 0
    try:
        with ai_log.open(encoding="utf-8", errors="ignore") as f:
            for row in csv.DictReader(f):
                t = (row.get("exit_time") or row.get("time") or "")[:10]
                try:
                    if datetime.strptime(t, "%Y-%m-%d").date() < cutoff:
                        continue
                except ValueError:
                    continue
                try:
                    ret = float(row.get("ret_pct") or 0)
                except ValueError:
                    ret = 0.0
                outcome = str(row.get("outcome") or "").strip().upper()
                if outcome in ("TP", "WIN") or ret > 0:
                    win_sum += ret
                    win_n += 1
                elif outcome in ("SL", "LOSS") or ret < 0:
                    loss_sum += ret
                    loss_n += 1
    except Exception:
        return None
    total = win_n + loss_n
    if total == 0:
        return None
    wr = win_n / total * 100
    avg = (win_sum + loss_sum) / total * 100
    pf_str = f"{win_sum / abs(loss_sum):.2f}" if loss_sum < 0 and win_sum > 0 else "-"
    status = "✅" if wr >= 44 else "⚠️" if wr >= 38 else "❌"
    return f"{status} AI学習ログ{lookback_weeks}週: WR={wr:.0f}% PF={pf_str} avg={avg:+.3f}% N={total}"


def _count_dormant_days(lookback_days: int = 21) -> Tuple[int, str]:
    """Count consecutive OBSERVE_OK=0 days from today backwards."""
    import csv as _csv
    today = datetime.now().date()
    consecutive = 0
    last_ok_date = ""
    for i in range(lookback_days):
        d = today - timedelta(days=i)
        log_f = LOGS_DIR / f"trade_log_{d.strftime('%Y%m%d')}.csv"
        if not log_f.exists():
            continue
        try:
            obs_ok = sum(
                1 for row in _csv.reader(log_f.open(encoding="utf-8", errors="ignore"))
                if len(row) >= 2 and row[1] == "OBSERVE_OK"
            )
        except Exception:
            obs_ok = 0
        if obs_ok == 0:
            consecutive += 1
        else:
            last_ok_date = d.strftime("%Y/%m/%d")
            break
    return consecutive, last_ok_date


def _count_weekly_trades(start8: str, end8: str) -> Tuple[int, int]:
    tp = sl = 0
    try:
        from datetime import datetime as dt
        start_d = dt.strptime(start8, "%Y%m%d").date()
        end_d = dt.strptime(end8, "%Y%m%d").date()
        cur = start_d
        while cur <= end_d:
            log_f = LOGS_DIR / f"trade_log_{cur.strftime('%Y%m%d')}.csv"
            if log_f.exists():
                import csv
                for row in csv.reader(log_f.open(encoding="utf-8", errors="ignore")):
                    if len(row) < 2:
                        continue
                    res = row[1]
                    if "TP" in res and "EXIT" in res:
                        tp += 1
                    if "SL" in res and "EXIT" in res:
                        sl += 1
            cur += timedelta(days=1)
    except Exception:
        pass
    return tp, sl


def _build_weekly_summary() -> str:
    state = _read_json(STATE_JSON)
    waf = state.get("_weekly_auto_feedback") or {}
    llm = waf.get("llm_feedback") or {}
    shadow_rev = waf.get("shadow_weekly_review") or {}
    shadow_incl = waf.get("shadow_inclusion") or {}
    fast_ma = waf.get("fast_ma_filter") or {}

    start8, end8 = _week_dates()
    week_tp, week_sl = _count_weekly_trades(start8, end8)
    week_total = week_tp + week_sl
    week_wr = f"{week_tp/week_total*100:.0f}%" if week_total > 0 else "N/A"

    status = "✅" if week_total > 0 and week_tp / week_total >= 0.44 else "⚠️" if week_total > 0 else "📭"

    ai_perf = _build_ai_perf_line(lookback_weeks=4)
    bot_ver = _read_bot_version()
    ver_str = f" {bot_ver}" if bot_ver else ""

    dormant_days, last_ok_date = _count_dormant_days()

    lines = [
        f"{status} Ouroboros 週次レポート{ver_str} {start8[:4]}/{start8[4:6]}/{start8[6:]}〜{end8[6:]}",
        "",
        f"週間 TP={week_tp} SL={week_sl} WR={week_wr}",
    ]
    if dormant_days >= 3:
        dormant_icon = "⚠️" if dormant_days >= 7 else "📭"
        dormant_ref = f"最終OBSERVE_OK: {last_ok_date}" if last_ok_date else "直近なし"
        lines.append(f"{dormant_icon} 休止継続{dormant_days}日 ({dormant_ref})")
    if ai_perf:
        lines.append(ai_perf)

    # AI auto-train result
    ai_train = waf.get("ai_auto_train") or {}
    if ai_train:
        new_th = ai_train.get("new_threshold", "?")
        old_th = ai_train.get("old_threshold", "?")
        samples = ai_train.get("samples_n", "?")
        lines.append(f"AI閾値: {old_th}→{new_th}  サンプル数={samples}")

    # Shadow inclusion decision
    if shadow_incl:
        decision = shadow_incl.get("decision", "-")
        lines.append(f"Shadow判定: {decision}")

    # Fast MA filter stats
    if fast_ma:
        ma_pct = fast_ma.get("ma_near_pct", 0)
        pass_rate = fast_ma.get("pass_rate_pct", 0)
        review = fast_ma.get("recommend_review", False)
        lines.append(f"fast_MA近接={ma_pct:.0f}%  通過率={pass_rate:.0f}%{'  ⚠️要レビュー' if review else ''}")

    # LLM suggestion
    if llm.get("used"):
        suggestion = str(llm.get("suggestion", "")).strip()
        if suggestion:
            lines.append(f"LLM提案: {suggestion[:80]}")

    # Shadow SL classification
    sl_cls = waf.get("shadow_sl_cls") or {}
    if isinstance(sl_cls, dict) and int(sl_cls.get("sl_n") or 0) > 0:
        rw_pct = float(sl_cls.get("reversal_wrap_pct") or 0.0)
        sl_n = int(sl_cls.get("sl_n") or 0)
        rw_icon = "⚠️" if rw_pct > 50 else ""
        lines.append(f"ShadowSL分類: SL={sl_n} reversal_wrap={rw_pct:.0f}%{rw_icon}")

    # Shadow weekly decision
    if shadow_rev:
        sd = shadow_rev.get("decision", "")
        if sd:
            lines.append(f"Shadow週次: {sd}")

    return "\n".join(lines)


def main() -> int:
    ntfy_url = _read_toml_str(SECRETS_TOML, "ntfy_topic_url")
    if not ntfy_url:
        print("[skip] ntfy_topic_url not configured")
        return 0

    body = _build_weekly_summary()
    start8, end8 = _week_dates()
    print("[ntfy] sending weekly summary")
    print(body)

    bearer = _read_toml_str(SECRETS_TOML, "ntfy_bearer_token")
    ok, msg = post_ntfy(
        ntfy_url,
        f"Ouroboros Weekly {datetime.now().strftime('%Y/%m/%d')}",
        body,
        level=LEVEL_INFO,
        tags="bar_chart,weekly_summary",
        bearer=bearer,
        state_path=NOTIFY_STATE,
        event_code=f"weekly_summary_{start8}_{end8}",
    )
    if ok:
        print(f"[OK] ntfy sent: {msg}")
    else:
        print(f"[WARN] ntfy failed: {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
