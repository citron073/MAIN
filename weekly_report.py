import csv
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict
from typing import Optional, Dict, Any, List, Tuple

# ===== 設定（bot.py と揃える）=====
START_HOUR = 10
END_HOUR = 16  # 16時は含めない（10:00-15:59）

SPREAD_THRESHOLD_PCT = 0.0500  # 0.05%（trade_logのspread_pctは「%」表記の数値想定）
DAYS = 7  # 直近何日を見るか

# ===== rollback監査（tune_override.json と同期する想定）=====
ROLLBACK_MIN_EXITS_REQUIRED = 9   # min_exits_required
ROLLBACK_TP_RATE_MIN = 25.0       # tp_rate_min
ROLLBACK_SL_RATE_MAX = 15.0       # sl_rate_max
ROLLBACK_TIMEOUT_RATE_MAX = 80.0  # timeout_rate_max

# ===== 監査強化：抜粋の前後行数 =====
CONTEXT_N = 2  # entry/exit の前後何行を抜粋するか（rows_all ベース）

# ===== 監査強化：note例の表示件数 =====
NOTE_EXAMPLES_N = 3

# ===== 監査強化：loose候補の上限 =====
LOOSE_CANDIDATES_TOPN = 10
LOOSE_CANDIDATES_NOTE_EXAMPLES_N = 3

# ===== 追加：loose分布表示のしきい値 =====
LOOSE_DISTRIBUTION_MIN_MATCHES = 20  # 週全体でlooseマッチがこの件数以上なら分布を出す
LOOSE_DISTRIBUTION_TOPN = 10         # 分布の上位表示数

# MAIN/weekly_report.py から見て ../logs
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

# ===== pos_id抽出（厳格）=====
# 期待形式: pos_id=YYYYMMDD-HHMMSS-AAA-999
POS_ID_RE_STRICT = re.compile(r"pos_id=([0-9]{8}-[0-9]{6}-[A-Z]+-\d{3})")

# ===== pos_id抽出（緩め）=====
# 例：pos-id:20260201_153012_buy_001 / POSID 20260201-153012-BUY-1 / pos_id=20260201-153012-BUY-0001
# 「日付8桁」＋「時刻6桁」＋「英字1〜10」＋「数字1〜6」を、区切りの揺れを許して拾う
POS_ID_RE_LOOSE = re.compile(
    r"(?i)\bpos[\s_\-]*id\b\D{0,6}([0-9]{8})[\s_\-:]{0,3}([0-9]{6})[\s_\-:]{0,3}([a-z]{1,10})[\s_\-:]{0,3}(\d{1,6})\b"
)

# 「pos_id」という語があるか（フォーマット崩れの目視用）
POS_ID_WORD_RE = re.compile(r"pos[\s_\-]*id", re.IGNORECASE)


def list_files_last_n_days(n: int = DAYS) -> List[Path]:
    files: List[Path] = []
    for i in range(n):
        day8 = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        p = LOGS_DIR / f"trade_log_{day8}.csv"
        if p.exists():
            files.append(p)
    return sorted(files)


def parse_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def in_time_window(dt: datetime) -> bool:
    return START_HOUR <= dt.hour < END_HOUR


def to_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def note_preview(s: Any, max_len: int = 160) -> str:
    if s is None:
        return ""
    t = str(s).strip().replace("\n", "\\n")
    return t if len(t) <= max_len else (t[:max_len] + "...")


def extract_pos_id_strict(note: Any) -> Optional[str]:
    if note is None:
        return None
    s = str(note)
    m = POS_ID_RE_STRICT.search(s)
    return m.group(1) if m else None


def extract_pos_id_loose_candidates(note: Any) -> List[str]:
    """
    note から「pos_idっぽい候補」を複数返す（厳格では拾えない崩れを救う）
    - 返す候補は正規化して pos_id風にする（ただし“候補”であって確定ではない）
    """
    if note is None:
        return []
    s = str(note)
    out: List[str] = []
    for m in POS_ID_RE_LOOSE.finditer(s):
        ymd = m.group(1)
        hms = m.group(2)
        tag = m.group(3).upper()
        num = m.group(4)
        # numは3桁に寄せる（超えてたらそのまま）
        if len(num) <= 3:
            num_norm = num.zfill(3)
        else:
            num_norm = num
        out.append(f"{ymd}-{hms}-{tag}-{num_norm}")
    # 重複排除（順序維持）
    seen = set()
    uniq: List[str] = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def classify_result(res: str) -> Dict[str, int]:
    r = (res or "").strip()

    out = {
        "PAPER": 0,
        "PAPER_EXIT": 0,
        "EXIT_TP": 0,
        "EXIT_SL": 0,
        "EXIT_TIMEOUT": 0,
        "EXIT_PARTIAL_TP": 0,
        "HOLD_OPEN_POS": 0,
        "OBSERVE": 0,
        "SKIP_SPREAD": 0,
        "SKIP_NEWS": 0,
        "SKIP_DAILY_LIMIT": 0,
        "SKIP_TICKER_INCOMPLETE": 0,
        "SKIP_OTHER": 0,
        "OTHER": 0,
    }

    if r == "PAPER":
        out["PAPER"] = 1
        return out

    if r.startswith("PAPER_EXIT_") or r == "PAPER_EXIT_PARTIAL_TP":
        out["PAPER_EXIT"] = 1
        if r == "PAPER_EXIT_TP":
            out["EXIT_TP"] = 1
        elif r == "PAPER_EXIT_SL":
            out["EXIT_SL"] = 1
        elif r == "PAPER_EXIT_TIMEOUT":
            out["EXIT_TIMEOUT"] = 1
        elif r == "PAPER_EXIT_PARTIAL_TP":
            out["EXIT_PARTIAL_TP"] = 1
        return out

    if r == "HOLD_OPEN_POS":
        out["HOLD_OPEN_POS"] = 1
        return out

    if r.startswith("OBSERVE"):
        out["OBSERVE"] = 1
        return out

    if r == "SKIP_SPREAD":
        out["SKIP_SPREAD"] = 1
        return out
    if r == "SKIP_NEWS":
        out["SKIP_NEWS"] = 1
        return out
    if r == "SKIP_DAILY_LIMIT":
        out["SKIP_DAILY_LIMIT"] = 1
        return out
    if r == "SKIP_TICKER_INCOMPLETE":
        out["SKIP_TICKER_INCOMPLETE"] = 1
        return out

    if r.startswith("SKIP_"):
        out["SKIP_OTHER"] = 1
        return out

    out["OTHER"] = 1
    return out


def read_rows(paths: List[Path], apply_filter: bool = True) -> List[Dict[str, Any]]:
    all_rows: List[Dict[str, Any]] = []
    for p in paths:
        try:
            with open(p, newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    t = (row.get("time") or "").strip()
                    dt = parse_dt(t)
                    if not dt:
                        continue
                    if apply_filter and (not in_time_window(dt)):
                        continue

                    row["_file"] = p.name
                    row["_day"] = dt.strftime("%Y-%m-%d")
                    row["_hour"] = dt.hour
                    row["_dt"] = dt

                    note = row.get("note")
                    row["_pos_id"] = extract_pos_id_strict(note)
                    row["_pos_id_loose"] = extract_pos_id_loose_candidates(note)

                    all_rows.append(row)
        except Exception:
            continue

    all_rows.sort(key=lambda x: x.get("_dt") or datetime.min)
    return all_rows


def build_rows_by_day(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_day[r.get("_day", "UNKNOWN_DAY")].append(r)
    for day in by_day:
        by_day[day].sort(key=lambda x: x.get("_dt") or datetime.min)
    return by_day


def pct(n: int, d: int) -> float:
    if d <= 0:
        return 0.0
    return (n / d) * 100.0


def fmt_duration(td: timedelta) -> str:
    total_sec = int(td.total_seconds())
    if total_sec < 0:
        total_sec = 0
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def row_compact(r: Dict[str, Any]) -> str:
    t = (r.get("time") or "").strip()
    res = (r.get("result") or "").strip()
    side = (r.get("side") or "").strip()
    price = (r.get("price") or "").strip()
    ltp = (r.get("ltp") or "").strip()
    pid = r.get("_pos_id") or ""
    note = (r.get("note") or "").strip()
    note_short = note if len(note) <= 120 else (note[:120] + "...")
    pid_part = f" pos_id={pid}" if pid else ""
    side_part = f" {side}" if side else ""
    price_part = f" price={price}" if price else ""
    ltp_part = f" ltp={ltp}" if ltp else ""
    return f"{t} | {res}{side_part}{price_part}{ltp_part}{pid_part} | {note_short}"


def build_pos_index(all_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    ※ entry/exit の確定は厳格pos_id（_pos_id）で作る
    ※ loose候補は欠損原因調査用（indexには入れない：誤結合を避ける）
    """
    idx: Dict[str, Dict[str, Any]] = {}
    for i, r in enumerate(all_rows):
        pid = r.get("_pos_id")
        if not pid:
            continue
        dt = r.get("_dt")
        if not dt:
            continue
        res = (r.get("result") or "").strip()

        if pid not in idx:
            idx[pid] = {"entry_dt": None, "exit_dt": None, "entry_i": None, "exit_i": None}

        if res == "PAPER" and idx[pid]["entry_dt"] is None:
            idx[pid]["entry_dt"] = dt
            idx[pid]["entry_i"] = i

        if (res.startswith("PAPER_EXIT_") or res == "PAPER_EXIT_PARTIAL_TP") and idx[pid]["exit_dt"] is None:
            idx[pid]["exit_dt"] = dt
            idx[pid]["exit_i"] = i
    return idx


def compute_entry_exit_duration(
    pos_index: Dict[str, Dict[str, Any]], pos_id: str
) -> Tuple[Optional[datetime], Optional[datetime], Optional[timedelta]]:
    if pos_id not in pos_index:
        return None, None, None
    e = pos_index[pos_id].get("entry_dt")
    x = pos_index[pos_id].get("exit_dt")
    if e is not None and x is not None:
        return e, x, (x - e)
    return e, x, None


def slice_context(all_rows: List[Dict[str, Any]], center_i: int, n: int = CONTEXT_N) -> List[Dict[str, Any]]:
    if center_i is None or center_i < 0 or center_i >= len(all_rows):
        return []
    lo = max(0, center_i - n)
    hi = min(len(all_rows) - 1, center_i + n)
    return all_rows[lo:hi + 1]


def pick_note_examples(day_rows_all: List[Dict[str, Any]], limit: int = NOTE_EXAMPLES_N) -> Dict[str, List[str]]:
    with_pos_id: List[str] = []
    without_pos_id: List[str] = []
    has_pos_word_but_no_extract: List[str] = []

    for r in day_rows_all:
        note = r.get("note")
        if note is None:
            continue
        note_s = str(note).strip()
        if note_s == "":
            continue

        pid = r.get("_pos_id")
        if pid:
            if len(with_pos_id) < limit:
                with_pos_id.append(note_preview(note_s))
            continue

        if len(without_pos_id) < limit:
            without_pos_id.append(note_preview(note_s))

        if POS_ID_WORD_RE.search(note_s) and len(has_pos_word_but_no_extract) < limit:
            has_pos_word_but_no_extract.append(note_preview(note_s))

        if (len(with_pos_id) >= limit and
            len(without_pos_id) >= limit and
            len(has_pos_word_but_no_extract) >= limit):
            break

    return {
        "with_pos_id": with_pos_id,
        "without_pos_id": without_pos_id,
        "has_pos_word_but_no_extract": has_pos_word_but_no_extract,
    }


def loose_candidates_report(day_rows_all: List[Dict[str, Any]]) -> Tuple[List[Tuple[str, int]], Dict[str, List[str]]]:
    cnt = Counter()
    examples: Dict[str, List[str]] = defaultdict(list)

    for r in day_rows_all:
        if r.get("_pos_id"):
            continue

        note = r.get("note")
        if note is None:
            continue
        note_s = str(note).strip()
        if note_s == "":
            continue

        cands = r.get("_pos_id_loose") or []
        for c in cands:
            cnt[c] += 1
            if len(examples[c]) < LOOSE_CANDIDATES_NOTE_EXAMPLES_N:
                examples[c].append(note_preview(note_s))

    top = cnt.most_common(LOOSE_CANDIDATES_TOPN)
    return top, examples


def loose_distribution(rows_all: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    rows_all（フィルタ無し）から loose抽出の分布を作る
    - tag別
    - num桁数別
    - tag×桁数 の組み合わせ
    ※ 厳格pos_idが取れている行は対象外（崩れ分析なので）
    """
    tag_cnt = Counter()
    numlen_cnt = Counter()
    tag_numlen_cnt = Counter()
    total_matches = 0
    total_rows_with_loose = 0

    for r in rows_all:
        if r.get("_pos_id"):
            continue
        note = r.get("note")
        if note is None:
            continue
        s = str(note)
        if s.strip() == "":
            continue

        # ここは candidates ではなく “生match” を数える（分布用）
        matches = list(POS_ID_RE_LOOSE.finditer(s))
        if not matches:
            continue

        total_rows_with_loose += 1
        for m in matches:
            total_matches += 1
            tag = (m.group(3) or "").upper()
            num = (m.group(4) or "")
            nlen = len(num)

            tag_cnt[tag] += 1
            numlen_cnt[nlen] += 1
            tag_numlen_cnt[(tag, nlen)] += 1

    return {
        "total_matches": total_matches,
        "total_rows_with_loose": total_rows_with_loose,
        "tag_cnt": tag_cnt,
        "numlen_cnt": numlen_cnt,
        "tag_numlen_cnt": tag_numlen_cnt,
    }


def summarize_loose_distribution(dist: Dict[str, Any]) -> List[str]:
    """
    分布から「崩れパターンの当たり」を短文で要約する（事実ベース）
    """
    total = int(dist.get("total_matches", 0))
    tag_cnt: Counter = dist.get("tag_cnt", Counter())
    numlen_cnt: Counter = dist.get("numlen_cnt", Counter())
    tag_numlen_cnt: Counter = dist.get("tag_numlen_cnt", Counter())

    lines: List[str] = []
    if total <= 0:
        return lines

    # 1位tag
    top_tag = tag_cnt.most_common(1)
    if top_tag:
        tag, c = top_tag[0]
        lines.append(f"最多tagは {tag}（{c}件 / {pct(c, total):.1f}%）。tag表記ゆれはこの周辺が主戦場の可能性。")

    # num桁
    top_num = numlen_cnt.most_common(1)
    if top_num:
        nlen, c = top_num[0]
        lines.append(f"最多の番号桁数は {nlen}桁（{c}件 / {pct(c, total):.1f}%）。ゼロ埋め/桁揺れの疑い。")

    # 組み合わせ上位
    top_combo = tag_numlen_cnt.most_common(1)
    if top_combo:
        (tag, nlen), c = top_combo[0]
        lines.append(f"最多の組み合わせは {tag}×{nlen}桁（{c}件 / {pct(c, total):.1f}%）。まずここからフォーマット統一が効きやすい。")

    return lines


def print_loose_distribution_block(title: str, dist: Dict[str, Any]) -> None:
    total = int(dist.get("total_matches", 0))
    rows_n = int(dist.get("total_rows_with_loose", 0))
    tag_cnt: Counter = dist.get("tag_cnt", Counter())
    numlen_cnt: Counter = dist.get("numlen_cnt", Counter())
    tag_numlen_cnt: Counter = dist.get("tag_numlen_cnt", Counter())

    print(title)
    print(f"  ・loose match 総数: {total}（loose検出行数: {rows_n}）")

    if total <= 0:
        print("  ・該当なし")
        return

    print(f"  ・tag別 上位{LOOSE_DISTRIBUTION_TOPN}")
    for tag, c in tag_cnt.most_common(LOOSE_DISTRIBUTION_TOPN):
        print(f"    - {tag}: {c}（{pct(c, total):.1f}%）")

    print(f"  ・番号桁数（num）別 上位{LOOSE_DISTRIBUTION_TOPN}")
    for nlen, c in numlen_cnt.most_common(LOOSE_DISTRIBUTION_TOPN):
        print(f"    - {nlen}桁: {c}（{pct(c, total):.1f}%）")

    print(f"  ・tag×桁数 上位{LOOSE_DISTRIBUTION_TOPN}")
    for (tag, nlen), c in tag_numlen_cnt.most_common(LOOSE_DISTRIBUTION_TOPN):
        print(f"    - {tag}×{nlen}桁: {c}（{pct(c, total):.1f}%）")

    summary = summarize_loose_distribution(dist)
    if summary:
        print("  ・自動要約（事実ベース）")
        for s in summary:
            print(f"    - {s}")


def main():
    files = list_files_last_n_days(DAYS)
    if not files:
        print(f"[ERROR] 直近{DAYS}日分の trade_log_YYYYMMDD.csv が見つかりません")
        print(f"  logs_dir: {LOGS_DIR}")
        return

    rows = read_rows(files, apply_filter=True)
    rows_all = read_rows(files, apply_filter=False)

    if not rows:
        start_day = files[0].stem.replace("trade_log_", "")
        end_day = files[-1].stem.replace("trade_log_", "")
        print(f"週次レポート（{start_day} 〜 {end_day}）")
        print(f"FILTER: {START_HOUR:02d}:00-{END_HOUR:02d}:00（{END_HOUR}は含めない）")
        print(f"LOGS_DIR: {LOGS_DIR}")
        print("")
        print("[INFO] データがありません（10:00-16:00フィルタ後）")
        print("  ※ rows_all（フィルタ無し）にデータがあっても、レポート本体は FILTER後が母集団です")
        return

    start_day = files[0].stem.replace("trade_log_", "")
    end_day = files[-1].stem.replace("trade_log_", "")

    rows_by_day = build_rows_by_day(rows)
    rows_all_by_day = build_rows_by_day(rows_all)
    pos_index = build_pos_index(rows_all)

    spreads: List[float] = []
    for r in rows:
        s = to_float(r.get("spread_pct"))
        if s is not None:
            spreads.append(s)

    trend_cnt = Counter((r.get("trend") or "UNKNOWN") for r in rows)
    signal_cnt = Counter((r.get("signal") or "NONE") for r in rows)

    cat = Counter()
    exit_break = Counter()
    for r in rows:
        c = classify_result(r.get("result", ""))
        cat.update({k: v for k, v in c.items() if v})
        if c["PAPER_EXIT"]:
            if c["EXIT_TP"]:
                exit_break["TP"] += 1
            elif c["EXIT_SL"]:
                exit_break["SL"] += 1
            elif c["EXIT_TIMEOUT"]:
                exit_break["TIMEOUT"] += 1
            elif c["EXIT_PARTIAL_TP"]:
                exit_break["PARTIAL_TP"] += 1
            else:
                exit_break["OTHER"] += 1

    daily = defaultdict(lambda: {
        "total": 0,
        "PAPER": 0,
        "PAPER_EXIT": 0,
        "OBSERVE": 0,
        "HOLD_OPEN_POS": 0,
        "SKIP_SPREAD": 0,
        "SKIP_NEWS": 0,
        "SKIP_DAILY_LIMIT": 0,
        "SKIP_TICKER_INCOMPLETE": 0,
        "spreads": [],
    })
    daily_exit = defaultdict(lambda: Counter({"TP": 0, "SL": 0, "TIMEOUT": 0, "PARTIAL_TP": 0, "OTHER": 0}))

    for r in rows:
        day = r.get("_day", "UNKNOWN_DAY")
        daily[day]["total"] += 1

        res = (r.get("result") or "").strip()
        c = classify_result(res)

        for k in [
            "PAPER", "PAPER_EXIT", "OBSERVE", "HOLD_OPEN_POS",
            "SKIP_SPREAD", "SKIP_NEWS", "SKIP_DAILY_LIMIT", "SKIP_TICKER_INCOMPLETE"
        ]:
            daily[day][k] += int(c.get(k, 0))

        if c["PAPER_EXIT"]:
            if c["EXIT_TP"]:
                daily_exit[day]["TP"] += 1
            elif c["EXIT_SL"]:
                daily_exit[day]["SL"] += 1
            elif c["EXIT_TIMEOUT"]:
                daily_exit[day]["TIMEOUT"] += 1
            elif c["EXIT_PARTIAL_TP"]:
                daily_exit[day]["PARTIAL_TP"] += 1
            else:
                daily_exit[day]["OTHER"] += 1

        s = to_float(r.get("spread_pct"))
        if s is not None:
            daily[day]["spreads"].append(s)

    hour_stats = defaultdict(lambda: {
        "total": 0,
        "PAPER": 0,
        "PAPER_EXIT": 0,
        "OBSERVE": 0,
        "HOLD_OPEN_POS": 0,
        "SKIP_SPREAD": 0,
        "SKIP_NEWS": 0,
        "spreads": [],
    })
    for r in rows:
        h = r.get("_hour", None)
        if h is None:
            continue
        hour_stats[h]["total"] += 1
        res = (r.get("result") or "").strip()
        c = classify_result(res)
        for k in ["PAPER", "PAPER_EXIT", "OBSERVE", "HOLD_OPEN_POS", "SKIP_SPREAD", "SKIP_NEWS"]:
            hour_stats[h][k] += int(c.get(k, 0))
        s = to_float(r.get("spread_pct"))
        if s is not None:
            hour_stats[h]["spreads"].append(s)

    candidates: List[int] = []
    for h, st in hour_stats.items():
        sp = st["spreads"]
        if sp:
            avg = sum(sp) / len(sp)
            if avg < SPREAD_THRESHOLD_PCT:
                candidates.append(h)
    candidates = sorted(candidates)

    # ===== 出力 =====
    print(f"週次レポート（{start_day} 〜 {end_day}）")
    print(f"FILTER: {START_HOUR:02d}:00-{END_HOUR:02d}:00（{END_HOUR}は含めない）")
    print(f"LOGS_DIR: {LOGS_DIR}")
    print(f"ROLLBACK_MIN_EXITS_REQUIRED: {ROLLBACK_MIN_EXITS_REQUIRED}")
    print(
        f"ROLLBACK_THRESHOLDS: tp<{ROLLBACK_TP_RATE_MIN:.1f}% / "
        f"sl>{ROLLBACK_SL_RATE_MAX:.1f}% / "
        f"timeout>{ROLLBACK_TIMEOUT_RATE_MAX:.1f}%"
    )
    print("")

    print("サマリー")
    print("① 集計")
    total = len(rows)
    print(f"  ・ログ件数：{total}")
    print(f"  ・OBSERVE：{cat.get('OBSERVE', 0)}")
    print(f"  ・HOLD_OPEN_POS：{cat.get('HOLD_OPEN_POS', 0)}")
    print(f"  ・SKIP_SPREAD：{cat.get('SKIP_SPREAD', 0)}")
    print(f"  ・SKIP_NEWS：{cat.get('SKIP_NEWS', 0)}")
    if cat.get("SKIP_DAILY_LIMIT", 0) > 0:
        print(f"  ・SKIP_DAILY_LIMIT：{cat.get('SKIP_DAILY_LIMIT', 0)}")
    if cat.get("SKIP_TICKER_INCOMPLETE", 0) > 0:
        print(f"  ・SKIP_TICKER_INCOMPLETE：{cat.get('SKIP_TICKER_INCOMPLETE', 0)}")
    if cat.get("SKIP_OTHER", 0) > 0:
        print(f"  ・SKIP_OTHER：{cat.get('SKIP_OTHER', 0)}")

    print(f"  ・PAPER：{cat.get('PAPER', 0)}")
    print(f"  ・PAPER_EXIT：{cat.get('PAPER_EXIT', 0)}")

    paper = int(cat.get("PAPER", 0))
    observe = int(cat.get("OBSERVE", 0))
    paper_rate = pct(paper, paper + observe) if (paper + observe) > 0 else 0.0
    print(f"  ・PAPER率（PAPER/(PAPER+OBSERVE)）：{paper_rate:.1f}%")

    print("")
    print("①b PAPER_EXIT内訳（週次）")
    exits = int(cat.get("PAPER_EXIT", 0))
    if exits > 0:
        tp = int(exit_break.get("TP", 0))
        sl = int(exit_break.get("SL", 0))
        to = int(exit_break.get("TIMEOUT", 0))
        pt = int(exit_break.get("PARTIAL_TP", 0))
        other = exits - (tp + sl + to + pt)
        if other < 0:
            other = 0
        print(f"  ・total: {exits}")
        print(f"  ・TP={tp}  SL={sl}  TIMEOUT={to}  PARTIAL_TP={pt}  OTHER={other}")
        print(f"  ・TP率={pct(tp, exits):.1f}%  SL率={pct(sl, exits):.1f}%  TIMEOUT率={pct(to, exits):.1f}%")
    else:
        print("  ・exitなし（PAPER_EXIT* がありません）")

    print("")
    print("② スプレッド状況（%）")
    if spreads:
        avg_sp = sum(spreads) / len(spreads)
        print(f"  ・平均：{avg_sp:.4f}%")
        print(f"  ・最小：{min(spreads):.4f}%")
        print(f"  ・最大：{max(spreads):.4f}%")
        print(f"  ・閾値：{SPREAD_THRESHOLD_PCT:.4f}%（固定）")
    else:
        print("  ・データなし")

    print("")
    print("③ 日別サマリー（件数 / 平均spread）")
    for day in sorted(daily.keys()):
        st = daily[day]
        sp = st["spreads"]
        avg = (sum(sp) / len(sp)) if sp else None
        avg_str = f"{avg:.4f}%" if avg is not None else "-"
        print(
            f"  ・{day}：{st['total']}件"
            f"（OBSERVE {st['OBSERVE']} / HOLD {st['HOLD_OPEN_POS']} / "
            f"SKIP_SPREAD {st['SKIP_SPREAD']} / SKIP_NEWS {st['SKIP_NEWS']} / "
            f"PAPER {st['PAPER']} / EXIT {st['PAPER_EXIT']}）"
            f" 平均 {avg_str}"
        )

    print("")
    print("③b 日別EXIT内訳（件数 / 率 / ROLLBACK_ELIGIBLE / WARN / DANGER / NOTE）")
    any_exit_day = False
    danger_days: List[str] = []

    for day in sorted(daily.keys()):
        exits_day = int(daily[day].get("PAPER_EXIT", 0))
        if exits_day <= 0:
            continue

        any_exit_day = True
        d = daily_exit[day]
        tp = int(d.get("TP", 0))
        sl = int(d.get("SL", 0))
        to = int(d.get("TIMEOUT", 0))
        pt = int(d.get("PARTIAL_TP", 0))
        other = int(d.get("OTHER", 0))

        total_break = tp + sl + to + pt + other
        diff = exits_day - total_break
        if diff != 0:
            other = max(0, other + diff)

        tp_rate = pct(tp, exits_day)
        sl_rate = pct(sl, exits_day)
        to_rate = pct(to, exits_day)

        eligible = exits_day >= ROLLBACK_MIN_EXITS_REQUIRED
        labels: List[str] = []
        note: str = ""
        day_has_danger = False

        if eligible:
            labels.append("ROLLBACK_ELIGIBLE")
            if tp_rate < ROLLBACK_TP_RATE_MIN:
                labels.append("DANGER_TP")
                day_has_danger = True
            if sl_rate > ROLLBACK_SL_RATE_MAX:
                labels.append("DANGER_SL")
                day_has_danger = True
            if to_rate > ROLLBACK_TIMEOUT_RATE_MAX:
                labels.append("DANGER_TIMEOUT")
                day_has_danger = True
        else:
            if tp_rate < ROLLBACK_TP_RATE_MIN:
                labels.append("WARN_TP")
            if sl_rate > ROLLBACK_SL_RATE_MAX:
                labels.append("WARN_SL")
            if to_rate > ROLLBACK_TIMEOUT_RATE_MAX:
                labels.append("WARN_TIMEOUT")
            note = f"(exits_day<{ROLLBACK_MIN_EXITS_REQUIRED}なので参考)"

        if eligible and day_has_danger:
            danger_days.append(day)

        label_str = (" | " + " ".join(labels)) if labels else ""
        note_str = f" {note}" if note else ""

        print(
            f"  ・{day}: total={exits_day}  "
            f"TP={tp} SL={sl} TIMEOUT={to} PARTIAL_TP={pt} OTHER={other}  "
            f"| TP率={tp_rate:.1f}% SL率={sl_rate:.1f}% TIMEOUT率={to_rate:.1f}%"
            f"{label_str}{note_str}"
        )

    if not any_exit_day:
        print("  ・該当なし（週内に PAPER_EXIT* がありません）")

    print("")
    print("③c DANGER日：pos_id監査（entry/exit 文脈）＋ 滞在時間（真の entry→exit）")
    print("    ※注意：③c は rows_all（フィルタ無し）が母集団（時間外含む完全文脈＆真の滞在時間）")
    if not danger_days:
        print("  ・該当なし（ROLLBACK_ELIGIBLE かつ DANGER_* の日がありません）")
    else:
        danger_pos_ids: Dict[str, List[str]] = defaultdict(list)

        for day in danger_days:
            day_rows = rows_by_day.get(day, [])
            for r in day_rows:
                res = (r.get("result") or "").strip()
                if not (res.startswith("PAPER_EXIT_") or res == "PAPER_EXIT_PARTIAL_TP"):
                    continue
                pid = r.get("_pos_id")
                if pid:
                    danger_pos_ids[day].append(pid)

        missing_summary: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: {
            "pos_id_missing": [],
            "entry_missing": [],
            "exit_missing": [],
            "entry_and_exit_missing": [],
        })

        for day in danger_days:
            pids = danger_pos_ids.get(day, [])
            seen = set()
            pids_u: List[str] = []
            for pid in pids:
                if pid in seen:
                    continue
                seen.add(pid)
                pids_u.append(pid)

            print(f"  ・{day}: DANGER対象 pos_id = {pids_u if pids_u else 'NOT_FOUND'}")

            if not pids_u:
                print("    - PAPER_EXIT行に pos_id(厳格) が見つかりません（note形式を確認）")
                missing_summary[day]["pos_id_missing"].append("NO_STRICT_POS_ID_IN_EXIT_ROWS")
                continue

            print("    pos_id | entry_time | exit_time | duration(HH:MM:SS)")
            print("    -----------------------------------------------------")
            for pid in pids_u:
                e_dt, x_dt, dur = compute_entry_exit_duration(pos_index, pid)
                e_s = e_dt.strftime("%Y-%m-%d %H:%M:%S") if e_dt else "NOT_FOUND"
                x_s = x_dt.strftime("%Y-%m-%d %H:%M:%S") if x_dt else "NOT_FOUND"
                d_s = fmt_duration(dur) if dur else "N/A"
                print(f"    {pid} | {e_s} | {x_s} | {d_s}")

                if (e_dt is None) and (x_dt is None):
                    missing_summary[day]["entry_and_exit_missing"].append(pid)
                elif e_dt is None:
                    missing_summary[day]["entry_missing"].append(pid)
                elif x_dt is None:
                    missing_summary[day]["exit_missing"].append(pid)

            print("")
            for pid in pids_u:
                e_dt, x_dt, dur = compute_entry_exit_duration(pos_index, pid)
                e_i = pos_index.get(pid, {}).get("entry_i")
                x_i = pos_index.get(pid, {}).get("exit_i")

                e_s = e_dt.strftime("%Y-%m-%d %H:%M:%S") if e_dt else "NOT_FOUND"
                x_s = x_dt.strftime("%Y-%m-%d %H:%M:%S") if x_dt else "NOT_FOUND"
                d_s = fmt_duration(dur) if dur else "N/A"

                print(f"    --- {pid} | true_entry={e_s} true_exit={x_s} duration={d_s} ---")

                if e_i is None:
                    print("    [ENTRY] NOT_FOUND（PAPER行が rows_all に無い可能性 / pos_id埋め込み漏れ）")
                else:
                    print("    [ENTRY context: rows_all]")
                    ctx = slice_context(rows_all, e_i, CONTEXT_N)
                    for rr in ctx:
                        mark = ">>" if rr is rows_all[e_i] else "  "
                        print(f"    {mark} {row_compact(rr)}")

                if x_i is None:
                    print("    [EXIT] NOT_FOUND（PAPER_EXIT行が rows_all に無い可能性 / pos_id埋め込み漏れ）")
                else:
                    print("    [EXIT context: rows_all]")
                    ctx = slice_context(rows_all, x_i, CONTEXT_N)
                    for rr in ctx:
                        mark = ">>" if rr is rows_all[x_i] else "  "
                        print(f"    {mark} {row_compact(rr)}")

                print("")

        print("③c-2 欠損検知（DANGER対象pos_idの entry/exit NOT_FOUND 一覧）")
        print("    目的：pos_id埋め込み漏れ / PAPER行・EXIT行の欠落 / ログ分断を早期発見")
        any_missing = False
        missing_days: List[str] = []

        for day in danger_days:
            ms = missing_summary.get(day, {})
            pos_id_missing = ms.get("pos_id_missing", [])
            entry_missing = ms.get("entry_missing", [])
            exit_missing = ms.get("exit_missing", [])
            both_missing = ms.get("entry_and_exit_missing", [])

            if pos_id_missing or entry_missing or exit_missing or both_missing:
                any_missing = True
                missing_days.append(day)
                print(f"  ・{day}")
                if pos_id_missing:
                    print(f"    - pos_id抽出不能（EXIT行に厳格pos_idなし等）: {pos_id_missing}")
                if both_missing:
                    print(f"    - entry&exit NOT_FOUND: {both_missing}")
                if entry_missing:
                    print(f"    - entry NOT_FOUND: {entry_missing}")
                if exit_missing:
                    print(f"    - exit NOT_FOUND: {exit_missing}")

        if not any_missing:
            print("  ・欠損なし（DANGER対象pos_idは全て entry/exit を rows_all で捕捉）")

        print("")
        print(f"③c-3 note例（欠損が出た日だけ / 各カテゴリ先頭{NOTE_EXAMPLES_N}件）")
        print("    目的：pos_id埋め込みフォーマット崩れを即発見（検知→原因特定を高速化）")

        if not any_missing:
            print("  ・欠損なしのため note例は省略")
        else:
            for day in missing_days:
                day_rows_all = rows_all_by_day.get(day, [])
                ex = pick_note_examples(day_rows_all, NOTE_EXAMPLES_N)

                print(f"  ・{day}")
                if ex["with_pos_id"]:
                    print("    [pos_id抽出OK(厳格) の note 例]")
                    for i, s in enumerate(ex["with_pos_id"], 1):
                        print(f"      {i}. {s}")
                else:
                    print("    [pos_id抽出OK(厳格) の note 例] なし")

                if ex["without_pos_id"]:
                    print("    [pos_id抽出NG(厳格) の note 例]")
                    for i, s in enumerate(ex["without_pos_id"], 1):
                        print(f"      {i}. {s}")
                else:
                    print("    [pos_id抽出NG(厳格) の note 例] なし（note自体が空/未出力の可能性）")

                if ex["has_pos_word_but_no_extract"]:
                    print("    [pos_id語はあるが厳格抽出できない例（崩れ候補）]")
                    for i, s in enumerate(ex["has_pos_word_but_no_extract"], 1):
                        print(f"      {i}. {s}")
                else:
                    print("    [pos_id語はあるが厳格抽出できない例] なし")

                top, examples = loose_candidates_report(day_rows_all)
                print("")
                print(f"    [LOOSE候補 抽出（上位{LOOSE_CANDIDATES_TOPN}）]")
                if not top:
                    print("      - 該当なし（pos_id語が無い / loose条件にも一致しない）")
                else:
                    for cand, c in top:
                        print(f"      - {cand} : {c}件")
                        ex_list = examples.get(cand, [])
                        for j, ns in enumerate(ex_list, 1):
                            print(f"          ex{j}. {ns}")

        # ===== 追加：LOOSE候補 分布（週全体 + 欠損日）=====
        print("")
        print("③d LOOSE候補の分布（tag別・桁数別）と自動要約")
        print("    ※注意：③d も rows_all（フィルタ無し）が母集団（時間外含む）")
        week_dist = loose_distribution(rows_all)

        if week_dist["total_matches"] >= LOOSE_DISTRIBUTION_MIN_MATCHES:
            print_loose_distribution_block("  ・週全体（rows_all）", week_dist)
        else:
            print(f"  ・週全体：loose matchが少ないため分布を省略（{week_dist['total_matches']}件 < {LOOSE_DISTRIBUTION_MIN_MATCHES}件）")

        if any_missing:
            for day in missing_days:
                day_rows_all = rows_all_by_day.get(day, [])
                d_dist = loose_distribution(day_rows_all)
                if d_dist["total_matches"] > 0:
                    print("")
                    print_loose_distribution_block(f"  ・{day}（欠損日）", d_dist)

    print("")
    print("④ MA環境認識（trend）")
    for k, v in trend_cnt.most_common():
        print(f"  ・{k}：{v}")

    print("")
    print("⑤ シグナル（signal）")
    for k, v in signal_cnt.most_common():
        print(f"  ・{k}：{v}")

    print("")
    print("⑥ 時間帯分析（hour別）")
    print("hour | total | OBSERVE | HOLD | SKIP_SPREAD | SKIP_NEWS | PAPER | EXIT | avg_spread(%)")
    print("----------------------------------------------------------------------------------------")
    for h in sorted(hour_stats.keys()):
        st = hour_stats[h]
        sp_list = st["spreads"]
        avg = (sum(sp_list) / len(sp_list)) if sp_list else None
        avg_str = f"{avg:.4f}" if avg is not None else "-"
        print(
            f"{h:>4} | {st['total']:>5} | {st['OBSERVE']:>7} | {st['HOLD_OPEN_POS']:>4} |"
            f" {st['SKIP_SPREAD']:>11} | {st['SKIP_NEWS']:>9} | {st['PAPER']:>5} | {st['PAPER_EXIT']:>4} | {avg_str:>12}"
        )

    print("")
    if candidates:
        print(f"稼働候補（平均spread < {SPREAD_THRESHOLD_PCT:.2f}%）: {candidates}")
    else:
        print(f"稼働候補（平均spread < {SPREAD_THRESHOLD_PCT:.2f}%）: 該当なし（データ不足 or 閾値未満なし）")

    print("")
    print("最終確認")
    print(f"  ・本体（①〜⑥）は直近{DAYS}日分を FILTER後(10-16)で集計")
    print("  ・③b は FILTER後の EXIT 内訳から WARN/DANGER を判定（exits_day<9 は参考注釈）")
    print("  ・③c は rows_all（フィルタ無し）で真の滞在時間＆文脈を監査")
    print("  ・③d は rows_all（フィルタ無し）で LOOSE抽出の分布を提示（tag/桁数/組み合わせ）")
    print("  ・LOOSE候補は原因調査用で、pos_index（entry/exit紐付け）には使用しない（誤結合防止）")


if __name__ == "__main__":
    main()
