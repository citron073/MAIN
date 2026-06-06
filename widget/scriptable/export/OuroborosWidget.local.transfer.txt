const DEFAULT_BASE_URLS = [
  "http://192.168.3.52:8787",
  "http://taninoMacBook-Air.local:8787",
];
const DEFAULT_TOKEN = "";
const REFRESH_MINUTES = 1;
const LAYOUT_VERSION = "8";

function resolveConfig() {
  const cfg = {
    baseUrls: [...DEFAULT_BASE_URLS],
    token: DEFAULT_TOKEN,
    previewFamily: "",
  };
  const raw = String(args.widgetParameter || "").trim();
  if (!raw) return cfg;

  try {
    const obj = JSON.parse(raw);
    if (Array.isArray(obj.baseUrls)) {
      cfg.baseUrls = obj.baseUrls.map((v) => String(v || "").trim()).filter(Boolean);
    } else if (obj.baseUrl) {
      cfg.baseUrls = [String(obj.baseUrl || "").trim()].filter(Boolean);
    }
    if (obj.token != null) cfg.token = String(obj.token || "");
    if (obj.previewFamily != null) cfg.previewFamily = String(obj.previewFamily || "");
    return cfg;
  } catch (_) {}

  const parts = raw.split(",").map((v) => v.trim()).filter(Boolean);
  for (const part of parts) {
    const idx = part.indexOf("=");
    if (idx <= 0) continue;
    const key = part.slice(0, idx).trim().toLowerCase();
    const value = part.slice(idx + 1).trim();
    if (!value) continue;
    if (key === "baseurl") cfg.baseUrls = [value];
    if (key === "token") cfg.token = value;
    if (key === "previewfamily") cfg.previewFamily = value;
  }
  return cfg;
}

const APP_CONFIG = resolveConfig();
const LEVEL_LABELS = { OK: "正常", WARN: "注意", ALERT: "警戒" };
const STAGE_LABELS = { LIVE: "本番", CANARY: "カナリア", PAPER: "ペーパー", SHADOW: "影運用" };
const DRIFT_LABELS = { NORMAL: "正常", INSUFFICIENT: "サンプル不足", ALERT: "警戒", PAUSED: "停止中" };

function keyOf(value) {
  return String(value || "").trim().toUpperCase();
}

function levelLabel(value) {
  return LEVEL_LABELS[keyOf(value)] || String(value || "-");
}

function stageLabel(value) {
  return STAGE_LABELS[keyOf(value)] || String(value || "-");
}

function driftLabel(value) {
  return DRIFT_LABELS[keyOf(value)] || String(value || "-");
}

function driftOutlook(drift) {
  return (drift && drift.resume_outlook) ? drift.resume_outlook : {};
}

function onOffLabel(flag) {
  return flag ? "ON" : "OFF";
}

function runnerLabel(flag) {
  return flag ? "稼働中" : "停止中";
}

function stopSummary(data) {
  if (data.risk_stop) return "リスク停止中";
  if (data.streak_stop) return "連敗停止中";
  return "通常";
}

function translateWarning(value) {
  const s = String(value || "").trim();
  if (!s) return "-";
  let m = s.match(/^drift gate remaining=(\d+)$/);
  if (m) return `ドリフト復帰まで残り ${m[1]} 件`;
  if (s === "streak_stop=ON") return "連敗停止が作動中";
  if (s === "risk_stop=ON") return "リスク停止が作動中";
  if (s === "trade_enabled=0") return "取引が無効";
  if (s === "runner=STOPPED" || s === "runner=OFF") return "bot が停止中";
  return s;
}

function headlineText(data, drift, compact) {
  if (compact) {
    return `${stageLabel(data.effective_stage)} / ${driftLabel(drift.status)}`;
  }
  return `${stageLabel(data.effective_stage)} / 取引 ${onOffLabel(data.trade_enabled)} / ${driftLabel(drift.status)}`;
}

function shortTimestamp(value) {
  const s = String(value || "").trim();
  return s ? s.replace(/^\d{4}-\d{2}-\d{2}\s+/, "") : "-";
}

function numberOrNull(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatJpy(value, digits = 0, withSign = false) {
  const num = numberOrNull(value);
  if (num == null) return "-";
  const text = Math.abs(num).toLocaleString("ja-JP", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  if (withSign) {
    if (num > 0) return `+${text}`;
    if (num < 0) return `-${text}`;
  }
  return num < 0 && !withSign ? `-${text}` : text;
}

function compactJpy(value, withSign = false) {
  const num = numberOrNull(value);
  if (num == null) return "-";
  const abs = Math.abs(num);
  let text = "";
  if (abs >= 10000) {
    const man = abs / 10000;
    text = `${man >= 100 ? man.toFixed(0) : man.toFixed(1).replace(/\.0$/, "")}万`;
  } else {
    text = abs.toLocaleString("ja-JP", { maximumFractionDigits: 0 });
  }
  if (withSign) {
    if (num > 0) return `+${text}`;
    if (num < 0) return `-${text}`;
  }
  return num < 0 && !withSign ? `-${text}` : text;
}

function goalValue(goal) {
  if (!goal || goal.goal_jpy == null) return "-";
  return `${formatJpy(goal.pnl_jpy, 0, true)} / ${formatJpy(goal.goal_jpy, 0, false)}`;
}

function resumeOutlookSummary(drift) {
  const outlook = driftOutlook(drift);
  if (outlook.summary) return String(outlook.summary);
  if (drift && drift.resume_ready) return "復帰OK";
  return `残り ${drift && drift.remaining_samples != null ? drift.remaining_samples : "-"}`;
}

function resumeOutlookShort(drift) {
  const outlook = driftOutlook(drift);
  if (outlook.short) return String(outlook.short);
  if (drift && drift.resume_ready) return "復帰OK";
  return `あと${drift && drift.remaining_samples != null ? drift.remaining_samples : "-"}件`;
}

function resumeOutlookDetail(drift) {
  const outlook = driftOutlook(drift);
  if (outlook.detail) return String(outlook.detail);
  return `約定 ${drift && drift.closed_n != null ? drift.closed_n : "-"} / ${drift && drift.min_recent_closed != null ? drift.min_recent_closed : "-"}`;
}

function goalCompactText(goal) {
  if (!goal || goal.goal_jpy == null) return "日次 -";
  return `日次 ${compactJpy(goal.pnl_jpy, true)} / ${compactJpy(goal.goal_jpy, false)}`;
}

function goalDetailText(goal) {
  if (!goal || goal.goal_jpy == null) return "-";
  return goal.achieved ? "達成済み" : `残り ${formatJpy(goal.remaining_jpy, 0, false)}`;
}

function balanceValue(balance) {
  if (!balance || !balance.available) return "-";
  return `¥${formatJpy(balance.jpy, 0, false)}`;
}

function balanceCompactText(balance) {
  if (!balance || !balance.available) return "残高 -";
  return `${String(balance.label || "残高")} ${compactJpy(balance.jpy, false)}`;
}

function balanceDetailText(balance) {
  if (!balance || !balance.available) return "取得待ち";
  return String(balance.label || "残高");
}

function freshnessLabel(freshness) {
  if (!freshness || !freshness.status) return "鮮度 -";
  if (freshness.status === "OK") return "鮮度 正常";
  if (freshness.status === "WARN") return "鮮度 注意";
  return "鮮度 警戒";
}

function freshnessDetailText(freshness) {
  if (!freshness) return "-";
  return String(freshness.age_text || freshness.summary || "-");
}

function latestTradeReasonLabel(reason) {
  const key = keyOf(reason);
  if (!key) return "取引なし";
  if (key === "TP") return "利確";
  if (key === "SL") return "損切";
  if (key === "TIMEOUT") return "時間切れ";
  if (key === "EOD") return "EOD";
  if (key === "PARTIAL_TP") return "分割利確";
  if (key === "ENTRY") return "新規";
  return key;
}

function latestTradeShort(trade) {
  if (!trade || !trade.available) return "直近 取引なし";
  if (trade.kind === "EXIT") {
    return `直近 ${latestTradeReasonLabel(trade.reason)} ${compactJpy(trade.pnl_jpy, true)}`;
  }
  return `直近 ${latestTradeReasonLabel(trade.reason)} ${String(trade.side || "-")}`;
}

function latestTradeValue(trade) {
  if (!trade || !trade.available) return "取引なし";
  if (trade.kind === "EXIT") {
    return `${latestTradeReasonLabel(trade.reason)} ${formatJpy(trade.pnl_jpy, 0, true)}`;
  }
  return `${latestTradeReasonLabel(trade.reason)} ${String(trade.side || "-")}`;
}

function latestTradeDetailText(trade) {
  if (!trade || !trade.available) return "-";
  const time = shortTimestamp(trade.time || "-");
  if (trade.kind === "EXIT") {
    const ret = numberOrNull(trade.ret_pct);
    return ret == null ? `${time}` : `${time} / ${ret.toFixed(2)}%`;
  }
  return `${time} / ${formatJpy(trade.entry_price, 0, false)}`;
}

function weeklyValue(weekly) {
  if (!weekly || !weekly.available) return "-";
  const base = `${formatJpy(weekly.pnl_jpy_sum, 0, true)} / ${Number(weekly.win_rate_pct || 0).toFixed(0)}%`;
  const hint = weeklyHintText(weekly);
  return hint ? `${base}\n${hint}` : base;
}

function weeklyHintText(weekly) {
  if (!weekly) return "";
  const decision = String(weekly.shadow_decision || "").trim();
  const hint = String(weekly.pattern_hint || "").trim();
  if (decision && hint) return `${decision} / ${hint}`;
  return decision || hint || "";
}

function weeklyHintCompactText(weekly) {
  const hint = weeklyHintText(weekly);
  return hint ? `週次 ${hint}` : "";
}

function weeklyDetailText(weekly) {
  if (!weekly || !weekly.available) return "今週約定なし";
  const hint = weeklyHintText(weekly);
  return hint ? `close ${weekly.closed_n || 0} / ${hint}` : `close ${weekly.closed_n || 0} / ${weekly.start_day8 || "-"}-`;
}

function weeklyPillColors(weekly) {
  if (!weekly || !weekly.available) return neutralPillColors();
  const pnl = numberOrNull(weekly.pnl_jpy_sum);
  if (pnl != null && pnl > 0) return { fg: "#065f46", bg: "#d1fae5" };
  if (pnl != null && pnl < 0) return { fg: "#991b1b", bg: "#fee2e2" };
  return { fg: "#9a3412", bg: "#ffedd5" };
}

function reflectionAdjustText(reflection) {
  if (!reflection || !reflection.available) return "";
  const parts = [];
  const filterHint = String(reflection.shadow_filter_hint || "").trim();
  const htfHint = String(reflection.shadow_htf_hint || "").trim();
  const exitHint = String(reflection.shadow_exit_hint || "").trim();
  if (filterHint) parts.push(`filter ${filterHint}`);
  if (htfHint) parts.push(`htf ${htfHint}`);
  if (exitHint) parts.push(`exit ${exitHint}`);
  return parts.join(" / ");
}

function shadowDayValue(shadowDay) {
  if (!shadowDay || !shadowDay.available) return "影日次 -";
  return `${formatJpy(shadowDay.pnl_jpy_sum, 0, true)} / ${Number(shadowDay.closed_n || 0)}件`;
}

function shadowDayDetailText(shadowDay) {
  if (!shadowDay || !shadowDay.available) return "影約定なし";
  return `勝率 ${Number(shadowDay.win_rate_pct || 0).toFixed(0)}% / tech ${Number(shadowDay.exit_technical_n || 0)} / weak ${Number(shadowDay.weak_progress_exit_n || 0)} / pr ${Number(shadowDay.progress_reversal_exit_n || 0)} / nf ${Number(shadowDay.no_follow_through_exit_n || 0)} / trend ${Number(shadowDay.observe_trend_strength_weak_n || 0)} / h60 ${Number(shadowDay.observe_ai_block_htf60_countertrend_n || 0)} / cf ${Number(shadowDay.observe_ai_block_htf15_60_conflict_n || 0)} / timeout ${Number(shadowDay.plain_timeout_n ?? shadowDay.timeout_n ?? 0)}`;
}

function shadowDayCompactText(shadowDay) {
  if (!shadowDay || !shadowDay.available) return "影 -";
  return `影 ${compactJpy(shadowDay.pnl_jpy_sum, true)} / ${Number(shadowDay.closed_n || 0)}件 / tech${Number(shadowDay.exit_technical_n || 0)} / wp${Number(shadowDay.weak_progress_exit_n || 0)} / pr${Number(shadowDay.progress_reversal_exit_n || 0)} / nf${Number(shadowDay.no_follow_through_exit_n || 0)} / tw${Number(shadowDay.observe_trend_strength_weak_n || 0)} / h60${Number(shadowDay.observe_ai_block_htf60_countertrend_n || 0)} / cf${Number(shadowDay.observe_ai_block_htf15_60_conflict_n || 0)} / to${Number(shadowDay.plain_timeout_n ?? shadowDay.timeout_n ?? 0)}`;
}

function shadowDayPillColors(shadowDay) {
  if (!shadowDay || !shadowDay.available) return neutralPillColors();
  const pnl = numberOrNull(shadowDay.pnl_jpy_sum);
  if (pnl != null && pnl > 0) return { fg: "#065f46", bg: "#d1fae5" };
  if (pnl != null && pnl < 0) return { fg: "#991b1b", bg: "#fee2e2" };
  return { fg: "#9a3412", bg: "#ffedd5" };
}

function levelPillColors(level) {
  const key = keyOf(level);
  if (key === "OK") return { fg: "#ffffff", bg: "#059669" };
  if (key === "ALERT") return { fg: "#ffffff", bg: "#dc2626" };
  return { fg: "#ffffff", bg: "#d97706" };
}

function stagePillColors(stage) {
  const key = keyOf(stage);
  if (key === "LIVE") return { fg: "#1d4ed8", bg: "#dbeafe" };
  if (key === "CANARY") return { fg: "#b45309", bg: "#fef3c7" };
  if (key === "SHADOW") return { fg: "#0f766e", bg: "#ccfbf1" };
  return { fg: "#475569", bg: "#e2e8f0" };
}

function topStatusPill(data) {
  if (data.risk_stop) return { text: "リスク停止", fg: "#ffffff", bg: "#dc2626", size: 13 };
  if (data.streak_stop) return { text: "連敗停止", fg: "#ffffff", bg: "#c2410c", size: 12 };
  const tone = levelPillColors(data.status_level);
  return { text: levelLabel(data.status_level || "WARN"), fg: tone.fg, bg: tone.bg, size: 11 };
}

function topStagePill(data) {
  const tone = stagePillColors(data.effective_stage);
  return {
    text: stageLabel(data.effective_stage || "-"),
    fg: tone.fg,
    bg: tone.bg,
    size: data.risk_stop || data.streak_stop ? 10 : 11,
  };
}

function tradePillColors(flag) {
  return flag ? { fg: "#065f46", bg: "#d1fae5" } : { fg: "#475569", bg: "#e2e8f0" };
}

function runnerPillColors(flag) {
  return flag ? { fg: "#065f46", bg: "#d1fae5" } : { fg: "#9a3412", bg: "#ffedd5" };
}

function neutralPillColors() {
  return { fg: "#334155", bg: "#e2e8f0" };
}

function driftPillColors(status) {
  const key = keyOf(status);
  if (key === "NORMAL") return { fg: "#065f46", bg: "#d1fae5" };
  if (key === "INSUFFICIENT" || key === "ALERT") return { fg: "#9a3412", bg: "#ffedd5" };
  return neutralPillColors();
}

function remainingPillColors(remaining) {
  return Number(remaining ?? 0) > 0
    ? { fg: "#ffffff", bg: "#f59e0b" }
    : { fg: "#065f46", bg: "#d1fae5" };
}

function warningPillColors(value) {
  const s = String(value || "").trim();
  if (s === "risk_stop=ON") return { fg: "#ffffff", bg: "#dc2626" };
  return { fg: "#9a3412", bg: "#ffedd5" };
}

function goalPillColors(goal) {
  if (!goal || goal.goal_jpy == null) return neutralPillColors();
  return goal.achieved ? { fg: "#065f46", bg: "#d1fae5" } : { fg: "#9a3412", bg: "#ffedd5" };
}

function balancePillColors(balance) {
  if (!balance || !balance.available) return neutralPillColors();
  return { fg: "#1d4ed8", bg: "#dbeafe" };
}

function freshnessPillColors(freshness) {
  if (!freshness || !freshness.status) return neutralPillColors();
  if (freshness.status === "OK") return { fg: "#065f46", bg: "#d1fae5" };
  if (freshness.status === "WARN") return { fg: "#9a3412", bg: "#ffedd5" };
  return { fg: "#991b1b", bg: "#fee2e2" };
}

function latestTradePillColors(trade) {
  if (!trade || !trade.available) return neutralPillColors();
  if (trade.kind === "EXIT") {
    const pnl = numberOrNull(trade.pnl_jpy);
    if (pnl != null && pnl > 0) return { fg: "#065f46", bg: "#d1fae5" };
    if (pnl != null && pnl < 0) return { fg: "#991b1b", bg: "#fee2e2" };
    return { fg: "#9a3412", bg: "#ffedd5" };
  }
  return { fg: "#1d4ed8", bg: "#dbeafe" };
}

function addPill(parent, text, fg, bg, size = 11, options = {}) {
  const pill = parent.addStack();
  pill.layoutHorizontally();
  pill.centerAlignContent();
  pill.backgroundColor = new Color(bg);
  pill.cornerRadius = 999;
  pill.setPadding(
    options.paddingTop ?? 4,
    options.paddingRight ?? 8,
    options.paddingBottom ?? 4,
    options.paddingLeft ?? 8,
  );
  const t = pill.addText(String(text));
  t.font = Font.boldSystemFont(size);
  t.textColor = new Color(fg);
  return pill;
}

function addPillRow(widget, items, options = {}) {
  const row = widget.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  const visible = items.filter((item) => item && item.text);
  visible.forEach((item, idx) => {
    addPill(row, item.text, item.fg, item.bg, item.size || 11, options.pillOptions || {});
    if (idx < visible.length - 1) row.addSpacer(options.gap ?? 6);
  });
  return row;
}

function addCenteredPillRow(widget, items, options = {}) {
  const row = widget.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  if (options.leadingSpacer == null) row.addSpacer();
  else row.addSpacer(options.leadingSpacer);
  const visible = items.filter((item) => item && item.text);
  visible.forEach((item, idx) => {
    addPill(row, item.text, item.fg, item.bg, item.size || 11, options.pillOptions || {});
    if (idx < visible.length - 1) row.addSpacer(options.gap ?? 8);
  });
  if (options.trailingSpacer == null) row.addSpacer();
  else row.addSpacer(options.trailingSpacer);
  return row;
}

function addSummaryCardTo(parent, title, subtitle, tone, options = {}) {
  const safeTone = tone || { bg: "#ffffff", title: "#0f172a", subtitle: "#475569" };
  const card = parent.addStack();
  card.layoutVertically();
  card.backgroundColor = new Color(safeTone.bg);
  card.cornerRadius = 16;
  card.setPadding(options.paddingTop || 10, options.paddingRight || 12, options.paddingBottom || 10, options.paddingLeft || 12);
  if (options.width || options.height) card.size = new Size(options.width || 0, options.height || 0);
  const titleText = card.addText(String(title));
  titleText.font = Font.boldSystemFont(14);
  titleText.textColor = new Color(safeTone.title);
  titleText.lineLimit = options.titleLines || 2;
  titleText.minimumScaleFactor = 0.7;
  if (subtitle) {
    card.addSpacer(2);
    const subtitleText = card.addText(String(subtitle));
    subtitleText.font = Font.systemFont(11);
    subtitleText.textColor = new Color(safeTone.subtitle);
    subtitleText.textOpacity = 0.82;
    subtitleText.lineLimit = options.subtitleLines || 2;
    subtitleText.minimumScaleFactor = 0.7;
  }
  return card;
}

function addSummaryCard(widget, title, subtitle, tone) {
  return addSummaryCardTo(widget, title, subtitle, tone);
}

function addDetailSummaryCardTo(parent, title, lines, tone, options = {}) {
  const safeTone = tone || { bg: "#ffffff", title: "#0f172a", subtitle: "#475569" };
  const card = parent.addStack();
  card.layoutVertically();
  card.backgroundColor = new Color(safeTone.bg);
  card.cornerRadius = 16;
  card.setPadding(options.paddingTop || 10, options.paddingRight || 12, options.paddingBottom || 10, options.paddingLeft || 12);
  if (options.width || options.height) card.size = new Size(options.width || 0, options.height || 0);
  const titleText = card.addText(String(title));
  titleText.font = Font.boldSystemFont(14);
  titleText.textColor = new Color(safeTone.title);
  titleText.lineLimit = options.titleLines || 2;
  titleText.minimumScaleFactor = 0.7;

  const visible = Array.isArray(lines) ? lines.filter((line) => line && line.text) : [];
  visible.forEach((line, idx) => {
    card.addSpacer(idx === 0 ? 3 : 2);
    const text = card.addText(String(line.text));
    text.font = line.bold ? Font.boldSystemFont(line.size || 12) : Font.systemFont(line.size || 11);
    text.textColor = new Color(line.color || safeTone.subtitle);
    if (line.opacity != null) text.textOpacity = line.opacity;
    text.lineLimit = line.lineLimit || 1;
    text.minimumScaleFactor = line.minimumScaleFactor || 0.65;
  });
  return card;
}

function addDetailSummaryCard(widget, title, lines, tone) {
  return addDetailSummaryCardTo(widget, title, lines, tone);
}

function addInfoBandTo(parent, label, value, tone, options = {}) {
  const safeTone = tone || { bg: "#f8fafc", label: "#475569", value: "#0f172a" };
  const valueLines = Number(options.valueLines || 2);
  const band = parent.addStack();
  band.layoutVertically();
  band.backgroundColor = new Color(safeTone.bg);
  band.cornerRadius = 14;
  band.setPadding(options.paddingTop || 8, options.paddingRight || 10, options.paddingBottom || 8, options.paddingLeft || 10);
  if (options.width || options.height) band.size = new Size(options.width || 0, options.height || 0);
  const labelText = band.addText(String(label));
  labelText.font = Font.boldSystemFont(10);
  labelText.textColor = new Color(safeTone.label);
  labelText.textOpacity = 0.88;
  labelText.lineLimit = 1;
  band.addSpacer(2);
  const valueText = band.addText(String(value));
  valueText.font = Font.boldSystemFont(options.valueSize || 12);
  valueText.textColor = new Color(safeTone.value);
  valueText.lineLimit = valueLines;
  valueText.minimumScaleFactor = options.minimumScaleFactor || 0.65;
  return band;
}

function addInfoBand(widget, label, value, tone, options = {}) {
  return addInfoBandTo(widget, label, value, tone, options);
}

function addMediumTopRow(widget, data, drift, goal, balance, latestTrade, weekly, shadowDay) {
  const row = widget.addStack();
  row.layoutHorizontally();
  row.topAlignContent();
  row.addSpacer(14);

  const left = row.addStack();
  left.layoutVertically();
  left.size = new Size(174, 80);
  addDetailSummaryCardTo(
    left,
    headlineText(data, drift, false),
    [
      {
        text: `日次目標 ${goalValue(goal)}`,
        color: goal.achieved ? "#065f46" : "#9a3412",
        bold: true,
        size: 12,
      },
      {
        text: latestTradeShort(latestTrade),
        color: latestTradePillColors(latestTrade).fg,
        bold: false,
        size: 10,
      },
      {
        text: weeklyHintCompactText(weekly) || shadowDayCompactText(shadowDay),
        color: weeklyHintCompactText(weekly) ? weeklyPillColors(weekly).fg : shadowDayPillColors(shadowDay).fg,
        bold: false,
        size: 9,
        opacity: 0.82,
        minimumScaleFactor: 0.52,
      },
    ],
    { bg: "#ffffff", title: "#0f172a", subtitle: "#475569" },
    { width: 174, height: 80, paddingTop: 9, paddingRight: 10, paddingBottom: 9, paddingLeft: 10, titleLines: 2 },
  );

  row.addSpacer(8);

  const right = row.addStack();
  right.layoutVertically();
  right.size = new Size(92, 80);
  addInfoBandTo(
    right,
    String(balance.label || "残高"),
    balanceValue(balance),
    { bg: balancePillColors(balance).bg, label: "#475569", value: balancePillColors(balance).fg },
    { valueLines: 2, width: 92, height: 37, valueSize: 12, paddingTop: 7, paddingRight: 9, paddingBottom: 7, paddingLeft: 9 },
  );
  right.addSpacer(6);
  addInfoBandTo(
    right,
    "復帰見込み",
    resumeOutlookShort(drift),
    { bg: readyPillColors(drift.resume_ready).bg, label: "#475569", value: readyPillColors(drift.resume_ready).fg },
    { valueLines: 2, width: 92, height: 37, valueSize: 10, minimumScaleFactor: 0.72, paddingTop: 7, paddingRight: 9, paddingBottom: 7, paddingLeft: 9 },
  );
  row.addSpacer(0);
}

function infoGridColumnWidth(family) {
  const key = String(family || "medium").toLowerCase();
  if (key === "large" || key === "extralarge") return 138;
  return 128;
}

function addInfoGrid(widget, items, family) {
  const visible = items.filter((item) => item && item.label && item.value);
  const width = infoGridColumnWidth(family);
  const key = String(family || "medium").toLowerCase();
  const medium = key === "medium";
  for (let idx = 0; idx < visible.length; idx += 2) {
    const row = widget.addStack();
    row.layoutHorizontally();
    row.topAlignContent();
    if (medium) row.addSpacer(14);

    const left = row.addStack();
    left.layoutVertically();
    addInfoBandTo(left, visible[idx].label, visible[idx].value, visible[idx].tone, {
      valueLines: visible[idx].valueLines || 2,
      width,
      height: visible[idx].height || 0,
      valueSize: visible[idx].valueSize || 12,
      minimumScaleFactor: visible[idx].minimumScaleFactor || 0.65,
    });

    if (idx + 1 < visible.length) {
      row.addSpacer(8);
      const right = row.addStack();
      right.layoutVertically();
      addInfoBandTo(right, visible[idx + 1].label, visible[idx + 1].value, visible[idx + 1].tone, {
        valueLines: visible[idx + 1].valueLines || 2,
        width,
        height: visible[idx + 1].height || 0,
        valueSize: visible[idx + 1].valueSize || 12,
        minimumScaleFactor: visible[idx + 1].minimumScaleFactor || 0.65,
      });
    }
    if (medium) row.addSpacer(0);

    if (idx + 2 < visible.length) widget.addSpacer(6);
  }
}

function compactStopText(data) {
  if (data.risk_stop) return "リスク停止";
  if (data.streak_stop) return "連敗停止";
  return "停止なし";
}

function compactResumeText(drift) {
  return resumeOutlookShort(drift);
}

function compactTradeText(flag) {
  return flag ? "取引ON" : "取引OFF";
}

function compactBotText(flag) {
  return flag ? "bot稼働" : "bot停止";
}

function familyBadge(family) {
  const key = String(family || "medium").toLowerCase();
  if (key === "small") return { text: `小${LAYOUT_VERSION}`, fg: "#1e293b", bg: "#e2e8f0", size: 10 };
  if (key === "large" || key === "extralarge") return { text: `大${LAYOUT_VERSION}`, fg: "#312e81", bg: "#e0e7ff", size: 10 };
  return { text: `中${LAYOUT_VERSION}`, fg: "#0f766e", bg: "#ccfbf1", size: 10 };
}

function readyPillColors(flag) {
  return flag ? { fg: "#065f46", bg: "#d1fae5" } : neutralPillColors();
}

function progressPillColors(current, required) {
  const currentValue = Number(current);
  const requiredValue = Number(required);
  if (Number.isFinite(currentValue) && Number.isFinite(requiredValue) && requiredValue > 0 && currentValue >= requiredValue) {
    return { fg: "#065f46", bg: "#d1fae5" };
  }
  if (Number.isFinite(currentValue) && Number.isFinite(requiredValue) && requiredValue > 0) {
    return { fg: "#9a3412", bg: "#ffedd5" };
  }
  return neutralPillColors();
}

function addWarningRows(widget, warnings, maxCount) {
  const visible = Array.isArray(warnings) ? warnings.slice(0, maxCount) : [];
  visible.forEach((warning) => {
    widget.addSpacer(6);
    addInfoBand(widget, "注意", translateWarning(warning), {
      bg: warningPillColors(warning).bg,
      label: "#475569",
      value: warningPillColors(warning).fg,
    }, { valueLines: 3 });
  });
}

function levelColor(level) {
  const lv = String(level || "WARN").toUpperCase();
  if (lv === "OK") return new Color("#059669");
  if (lv === "ALERT") return new Color("#dc2626");
  return new Color("#d97706");
}

function bgGradient(level) {
  const g = new LinearGradient();
  g.locations = [0, 1];
  if (String(level || "WARN").toUpperCase() === "OK") {
    g.colors = [new Color("#ecfdf5"), new Color("#d1fae5")];
  } else if (String(level || "WARN").toUpperCase() === "ALERT") {
    g.colors = [new Color("#fef2f2"), new Color("#fee2e2")];
  } else {
    g.colors = [new Color("#fffbeb"), new Color("#fef3c7")];
  }
  return g;
}

function compactBgGradient(data, drift) {
  const g = new LinearGradient();
  g.locations = [0, 1];
  const remainingValue = Number(drift.remaining_samples);
  if (data.risk_stop) {
    g.colors = [new Color("#fff1f2"), new Color("#fecdd3")];
  } else if (data.streak_stop) {
    g.colors = [new Color("#fff7ed"), new Color("#fdba74")];
  } else if (Number.isFinite(remainingValue) && remainingValue <= 0 && drift.resume_ready) {
    g.colors = [new Color("#ecfdf5"), new Color("#bbf7d0")];
  } else if (String(drift.status || "").toUpperCase() === "INSUFFICIENT") {
    g.colors = [new Color("#fffbeb"), new Color("#fde68a")];
  } else {
    return bgGradient(data.status_level);
  }
  return g;
}

function compactHeroTone(data, drift) {
  data = data || {};
  drift = drift || {};
  const remainingValue = Number(drift.remaining_samples);
  if (data.risk_stop) {
    return { fg: "#9f1239", sub: "#be123c", bg: "#fff1f2" };
  }
  if (data.streak_stop) {
    return { fg: "#9a3412", sub: "#c2410c", bg: "#fff7ed" };
  }
  if (Number.isFinite(remainingValue) && remainingValue <= 0) {
    return { fg: "#065f46", sub: "#047857", bg: "#f0fdf4" };
  }
  return { fg: "#9a3412", sub: "#c2410c", bg: "#fff7ed" };
}

function addHeroMetric(widget, label, value, tone) {
  const safeTone = tone && tone.fg && tone.sub && tone.bg
    ? tone
    : { fg: "#9a3412", sub: "#c2410c", bg: "#fff7ed" };
  const box = widget.addStack();
  box.layoutVertically();
  box.backgroundColor = new Color(safeTone.bg);
  box.cornerRadius = 16;
  box.setPadding(8, 10, 8, 10);
  const labelText = box.addText(String(label));
  labelText.font = Font.boldSystemFont(10);
  labelText.textColor = new Color(safeTone.sub);
  labelText.textOpacity = 0.88;
  box.addSpacer(2);
  const valueText = box.addText(String(value));
  valueText.font = Font.boldSystemFont(28);
  valueText.textColor = new Color(safeTone.fg);
  return box;
}

function buildStatusUrl(baseUrl) {
  const root = String(baseUrl || "").replace(/\/$/, "");
  const suffix = APP_CONFIG.token ? `?token=${encodeURIComponent(APP_CONFIG.token)}` : "";
  return `${root}/widget-status.json${suffix}`;
}

function buildOpenUrl(baseUrl, family, latestReflection) {
  const root = String(baseUrl || "").replace(/\/$/, "");
  const suffix = APP_CONFIG.token ? `?token=${encodeURIComponent(APP_CONFIG.token)}` : "";
  const key = String(family || "").toLowerCase();
  const path = ((key === "large" || key === "extralarge") && latestReflection && latestReflection.available)
    ? "/daily-reflection"
    : "/";
  return `${root}${path}${suffix}`;
}

async function fetchStatus() {
  let lastErr = null;
  for (const baseUrl of APP_CONFIG.baseUrls) {
    try {
      const req = new Request(buildStatusUrl(baseUrl));
      req.timeoutInterval = 10;
      const data = await req.loadJSON();
      return { data, baseUrl };
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error("all endpoints failed");
}

function addLine(stack, text, size, opacity, colorHex) {
  const t = stack.addText(String(text));
  t.font = Font.systemFont(size);
  t.textOpacity = opacity;
  t.textColor = colorHex ? new Color(colorHex) : new Color("#0f172a");
  return t;
}

async function buildWidget() {
  const widget = new ListWidget();
  widget.backgroundGradient = bgGradient("WARN");
  widget.setPadding(14, 14, 14, 14);
  widget.refreshAfterDate = new Date(Date.now() + REFRESH_MINUTES * 60 * 1000);

  try {
    const { data, baseUrl } = await fetchStatus();
    const drift = data.drift || {};
    const goal = data.goal || {};
    const balance = data.balance || {};
    const freshness = data.freshness || {};
    const latestTrade = data.latest_trade || {};
    const weekly = data.weekly || {};
    const shadowDay = data.shadow_day || {};
    const latestReflection = data.latest_reflection || {};
    const family = String(config.widgetFamily || "medium");
    const compact = family === "small";
    const medium = family === "medium";
    const spacious = family === "large" || family === "extraLarge";
    widget.backgroundGradient = compact ? compactBgGradient(data, drift) : bgGradient(data.status_level);
    widget.url = buildOpenUrl(baseUrl, family, latestReflection);

    const statusTone = topStatusPill(data);
    const stageTone = topStagePill(data);
    const familyTone = familyBadge(family);
    addCenteredPillRow(widget, [statusTone, stageTone, familyTone], medium ? {
      leadingSpacer: 20,
      trailingSpacer: 2,
      gap: 6,
      pillOptions: { paddingTop: 2, paddingRight: 7, paddingBottom: 2, paddingLeft: 7 },
    } : {});

    widget.addSpacer(medium ? 6 : 8);
    if (compact) {
      addHeroMetric(widget, driftLabel(drift.status || "-"), `残り ${drift.remaining_samples ?? "-"}`, compactHeroTone(data, drift));
    } else if (medium) {
      addMediumTopRow(widget, data, drift, goal, balance, latestTrade, weekly, shadowDay);
    } else {
      addSummaryCard(
        widget,
        headlineText(data, drift, compact),
        `bot ${runnerLabel(data.runner_alive)} ・ 残り ${drift.remaining_samples ?? "-"} ・ ${stopSummary(data)}`,
        { bg: "#ffffff", title: "#0f172a", subtitle: "#475569" },
      );
    }
    widget.addSpacer(medium ? 3 : 6);

    if (compact) {
      addLine(widget, goalCompactText(goal), 11, 0.86, goal.achieved ? "#065f46" : "#9a3412");
      addLine(widget, balanceCompactText(balance), 10, 0.72, balance.available ? "#1d4ed8" : "#475569");
      const showResumeHint = String(drift.status || "").toUpperCase() === "INSUFFICIENT" || !drift.resume_ready;
      const compactNote = showResumeHint
        ? `復帰見込み ${resumeOutlookShort(drift)}`
        : (freshness.status && freshness.status !== "OK" ? `${freshnessLabel(freshness)} ${freshnessDetailText(freshness)}` : latestTradeShort(latestTrade));
      const compactNoteColor = showResumeHint
        ? (drift.resume_ready ? "#065f46" : "#9a3412")
        : (freshness.status === "ALERT"
          ? "#991b1b"
          : (freshness.status === "WARN" ? "#9a3412" : latestTradePillColors(latestTrade).fg));
      addLine(widget, compactNote, 10, 0.66, compactNoteColor);
      widget.addSpacer(6);
      addPillRow(widget, [
        {
          text: compactStopText(data),
          ...(data.risk_stop ? { fg: "#991b1b", bg: "#fee2e2" } : data.streak_stop ? { fg: "#9a3412", bg: "#ffedd5" } : neutralPillColors()),
        },
        { text: compactResumeText(drift), ...(drift.resume_ready ? { fg: "#065f46", bg: "#d1fae5" } : neutralPillColors()) },
      ]);
    } else if (medium) {
      addCenteredPillRow(widget, [
        { text: compactTradeText(data.trade_enabled), ...tradePillColors(data.trade_enabled) },
        { text: compactBotText(data.runner_alive), ...runnerPillColors(data.runner_alive) },
        { text: freshnessLabel(freshness).replace(/^鮮度\s+/, ""), ...freshnessPillColors(freshness) },
      ], {
        leadingSpacer: 18,
        trailingSpacer: 2,
        gap: 6,
        pillOptions: { paddingTop: 3, paddingRight: 7, paddingBottom: 3, paddingLeft: 7 },
      });
      widget.addSpacer(3);
      addInfoGrid(widget, [
        {
          label: "ドリフト",
          value: `${driftLabel(drift.status || "-")} / ${resumeOutlookShort(drift)}`,
          tone: { bg: driftPillColors(drift.status || "-").bg, label: "#475569", value: driftPillColors(drift.status || "-").fg },
          valueLines: 2,
          height: 40,
          valueSize: 10,
          minimumScaleFactor: 0.72,
        },
        {
          label: "停止 / 復帰",
          value: `${stopSummary(data)} / ${resumeOutlookSummary(drift)}`,
          tone: {
            bg: data.risk_stop ? "#fee2e2" : data.streak_stop ? "#ffedd5" : "#e2e8f0",
            label: "#475569",
            value: data.risk_stop ? "#991b1b" : data.streak_stop ? "#9a3412" : (drift.resume_ready ? "#065f46" : "#334155"),
          },
          valueLines: 2,
          height: 40,
          valueSize: 10,
          minimumScaleFactor: 0.72,
        },
      ], family);
    } else {
      const infoItems = [
        {
          label: "取引",
          value: onOffLabel(data.trade_enabled),
          tone: { bg: tradePillColors(data.trade_enabled).bg, label: "#475569", value: tradePillColors(data.trade_enabled).fg },
        },
        {
          label: "ドリフト",
          value: `${driftLabel(drift.status || "-")} / ${resumeOutlookShort(drift)}`,
          tone: { bg: driftPillColors(drift.status || "-").bg, label: "#475569", value: driftPillColors(drift.status || "-").fg },
          valueLines: 2,
        },
        {
          label: "日次目標",
          value: goalValue(goal),
          tone: { bg: goalPillColors(goal).bg, label: "#475569", value: goalPillColors(goal).fg },
          valueLines: 2,
        },
        {
          label: "残高",
          value: balanceValue(balance),
          tone: { bg: balancePillColors(balance).bg, label: "#475569", value: balancePillColors(balance).fg },
          valueLines: 2,
        },
      ];
      if (spacious) {
        infoItems.splice(3, 0,
          {
            label: "停止",
            value: stopSummary(data),
            tone: { bg: data.risk_stop ? "#fee2e2" : data.streak_stop ? "#ffedd5" : "#e2e8f0", label: "#475569", value: data.risk_stop ? "#991b1b" : data.streak_stop ? "#9a3412" : "#334155" },
          },
          {
            label: "復帰見込み",
            value: resumeOutlookSummary(drift),
            tone: { bg: readyPillColors(drift.resume_ready).bg, label: "#475569", value: readyPillColors(drift.resume_ready).fg },
            valueLines: 3,
          },
          {
            label: "鮮度",
            value: freshnessLabel(freshness),
            tone: { bg: freshnessPillColors(freshness).bg, label: "#475569", value: freshnessPillColors(freshness).fg },
            valueLines: 2,
          },
          {
            label: "直近",
            value: latestTradeValue(latestTrade),
            tone: { bg: latestTradePillColors(latestTrade).bg, label: "#475569", value: latestTradePillColors(latestTrade).fg },
            valueLines: 2,
          },
          {
            label: "今週累計",
            value: weeklyValue(weekly),
            tone: { bg: weeklyPillColors(weekly).bg, label: "#475569", value: weeklyPillColors(weekly).fg },
            valueLines: 2,
          },
          {
            label: "影日次",
            value: shadowDayValue(shadowDay),
            tone: { bg: shadowDayPillColors(shadowDay).bg, label: "#475569", value: shadowDayPillColors(shadowDay).fg },
            valueLines: 2,
          },
        );
        infoItems.push({
          label: "AI / 日次",
          value: `${data.ai_auto_train_enabled ? "学習ON" : "学習OFF"} / ${data.daily_loss_limit_pct ?? "-"}`,
          tone: { bg: "#e2e8f0", label: "#475569", value: "#1e293b" },
          valueLines: 2,
        });
        infoItems.push(
          {
            label: "直近確定",
            value: `${drift.closed_n ?? "-"}/${drift.min_recent_closed ?? "-"}`,
            tone: { bg: progressPillColors(drift.closed_n, drift.min_recent_closed).bg, label: "#475569", value: progressPillColors(drift.closed_n, drift.min_recent_closed).fg },
            valueLines: 2,
          },
          {
            label: "通常 / カナリア",
            value: `${drift.normal_streak ?? "-"}/${drift.required_normals ?? "-"} ・ ${drift.canary_streak ?? "-"}/${drift.canary_required ?? "-"}`,
            tone: { bg: readyPillColors(Number(drift.remaining_normals ?? 1) <= 0 && Boolean(drift.canary_ready)).bg, label: "#475569", value: readyPillColors(Number(drift.remaining_normals ?? 1) <= 0 && Boolean(drift.canary_ready)).fg },
            valueLines: 3,
          },
          {
            label: "影bot",
            value: runnerLabel(data.shadow_runner_alive),
            tone: { bg: runnerPillColors(data.shadow_runner_alive).bg, label: "#475569", value: runnerPillColors(data.shadow_runner_alive).fg },
            valueLines: 2,
          },
        );
      }
      addInfoGrid(widget, infoItems, family);
    }

    if (spacious && Array.isArray(data.warnings) && data.warnings.length) {
      addWarningRows(widget, data.warnings, spacious ? 2 : 1);
    }

    if (compact) {
      widget.addSpacer(4);
    } else if (spacious) {
      widget.addSpacer();
      addLine(widget, `${freshnessLabel(freshness)} / ${latestTradeDetailText(latestTrade)}`, 10, 0.58);
      if (latestReflection && latestReflection.available) {
        const adjust = reflectionAdjustText(latestReflection);
        addLine(
          widget,
          `反省 ${latestReflection.day8 || "-"} / ${latestReflection.goal_achieved ? "達成" : "未達"}${adjust ? ` / ${adjust}` : ""}`,
          10,
          0.54,
        );
      }
      addLine(widget, `更新 ${shortTimestamp(data.generated_at || "-")}`, 10, 0.55);
      addLine(widget, `最終ログ ${data.latest_trade_log_day || "-"}`, 10, 0.48);
    } else {
      widget.addSpacer(2);
    }
  } catch (err) {
    widget.backgroundGradient = bgGradient("ALERT");
    const title = widget.addText("取得エラー");
    title.font = Font.boldSystemFont(14);
    title.textColor = new Color("#dc2626");
    widget.addSpacer(8);
    addLine(widget, String(err), 11, 0.82);
  }

  return widget;
}

const widget = await buildWidget();
Script.setWidget(widget);

if (!config.runsInWidget) {
  const previewFamily = String((args.queryParameters && args.queryParameters.family) || APP_CONFIG.previewFamily || "medium").toLowerCase();
  if (previewFamily === "small") {
    await widget.presentSmall();
  } else if (previewFamily === "large" || previewFamily === "extralarge") {
    await widget.presentLarge();
  } else {
    await widget.presentMedium();
  }
}

Script.complete();
