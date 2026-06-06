const DEFAULT_BASE_URLS = [
  "http://taninoMacBook-Air.local:8787",
  "http://192.168.3.52:8787",
];
const DEFAULT_TOKEN = "";
const REFRESH_MINUTES = 1;

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

function shortTimestamp(value) {
  const s = String(value || "").trim();
  return s ? s.replace(/^\d{4}-\d{2}-\d{2}\s+/, "") : "-";
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

function addPill(parent, text, fg, bg, size = 11) {
  const pill = parent.addStack();
  pill.layoutHorizontally();
  pill.centerAlignContent();
  pill.backgroundColor = new Color(bg);
  pill.cornerRadius = 999;
  pill.setPadding(4, 8, 4, 8);
  const t = pill.addText(String(text));
  t.font = Font.boldSystemFont(size);
  t.textColor = new Color(fg);
  return pill;
}

function addPillRow(widget, items) {
  const row = widget.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  const visible = items.filter((item) => item && item.text);
  visible.forEach((item, idx) => {
    addPill(row, item.text, item.fg, item.bg, item.size || 11);
    if (idx < visible.length - 1) row.addSpacer(6);
  });
  return row;
}

function addCenteredPillRow(widget, items) {
  const row = widget.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  row.addSpacer();
  const visible = items.filter((item) => item && item.text);
  visible.forEach((item, idx) => {
    addPill(row, item.text, item.fg, item.bg, item.size || 11);
    if (idx < visible.length - 1) row.addSpacer(8);
  });
  row.addSpacer();
  return row;
}

function addSummaryCard(widget, title, subtitle, tone) {
  const safeTone = tone || { bg: "#ffffff", title: "#0f172a", subtitle: "#475569" };
  const card = widget.addStack();
  card.layoutVertically();
  card.backgroundColor = new Color(safeTone.bg);
  card.cornerRadius = 16;
  card.setPadding(10, 12, 10, 12);
  const titleText = card.addText(String(title));
  titleText.font = Font.boldSystemFont(14);
  titleText.textColor = new Color(safeTone.title);
  titleText.lineLimit = 2;
  titleText.minimumScaleFactor = 0.7;
  if (subtitle) {
    card.addSpacer(2);
    const subtitleText = card.addText(String(subtitle));
    subtitleText.font = Font.systemFont(11);
    subtitleText.textColor = new Color(safeTone.subtitle);
    subtitleText.textOpacity = 0.82;
    subtitleText.lineLimit = 2;
    subtitleText.minimumScaleFactor = 0.7;
  }
  return card;
}

function addInfoBandTo(parent, label, value, tone, options = {}) {
  const safeTone = tone || { bg: "#f8fafc", label: "#475569", value: "#0f172a" };
  const valueLines = Number(options.valueLines || 2);
  const band = parent.addStack();
  band.layoutVertically();
  band.backgroundColor = new Color(safeTone.bg);
  band.cornerRadius = 14;
  band.setPadding(8, 10, 8, 10);
  if (options.width) band.size = new Size(options.width, 0);
  const labelText = band.addText(String(label));
  labelText.font = Font.boldSystemFont(10);
  labelText.textColor = new Color(safeTone.label);
  labelText.textOpacity = 0.88;
  labelText.lineLimit = 1;
  band.addSpacer(2);
  const valueText = band.addText(String(value));
  valueText.font = Font.boldSystemFont(12);
  valueText.textColor = new Color(safeTone.value);
  valueText.lineLimit = valueLines;
  valueText.minimumScaleFactor = 0.65;
  return band;
}

function addInfoBand(widget, label, value, tone, options = {}) {
  return addInfoBandTo(widget, label, value, tone, options);
}

function infoGridColumnWidth(family) {
  const key = String(family || "medium").toLowerCase();
  if (key === "large" || key === "extralarge") return 138;
  return 138;
}

function addInfoGrid(widget, items, family) {
  const visible = items.filter((item) => item && item.label && item.value);
  const width = infoGridColumnWidth(family);
  for (let idx = 0; idx < visible.length; idx += 2) {
    const row = widget.addStack();
    row.layoutHorizontally();
    row.centerAlignContent();

    const left = row.addStack();
    left.layoutVertically();
    addInfoBandTo(left, visible[idx].label, visible[idx].value, visible[idx].tone, { valueLines: visible[idx].valueLines || 2, width });

    if (idx + 1 < visible.length) {
      row.addSpacer(8);
      const right = row.addStack();
      right.layoutVertically();
      addInfoBandTo(right, visible[idx + 1].label, visible[idx + 1].value, visible[idx + 1].tone, { valueLines: visible[idx + 1].valueLines || 2, width });
    }

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
  if (key === "small") return { text: "小", fg: "#1e293b", bg: "#e2e8f0", size: 10 };
  if (key === "large" || key === "extralarge") return { text: "大", fg: "#312e81", bg: "#e0e7ff", size: 10 };
  return { text: "中", fg: "#0f766e", bg: "#ccfbf1", size: 10 };
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
  const box = widget.addStack();
  box.layoutVertically();
  box.backgroundColor = new Color(tone.bg);
  box.cornerRadius = 16;
  box.setPadding(8, 10, 8, 10);
  const labelText = box.addText(String(label));
  labelText.font = Font.boldSystemFont(10);
  labelText.textColor = new Color(tone.sub);
  labelText.textOpacity = 0.88;
  box.addSpacer(2);
  const valueText = box.addText(String(value));
  valueText.font = Font.boldSystemFont(28);
  valueText.textColor = new Color(tone.fg);
  return box;
}

function buildStatusUrl(baseUrl) {
  const root = String(baseUrl || "").replace(/\/$/, "");
  const suffix = APP_CONFIG.token ? `?token=${encodeURIComponent(APP_CONFIG.token)}` : "";
  return `${root}/widget-status.json${suffix}`;
}

function buildOpenUrl(baseUrl) {
  const root = String(baseUrl || "").replace(/\/$/, "");
  const suffix = APP_CONFIG.token ? `?token=${encodeURIComponent(APP_CONFIG.token)}` : "";
  return `${root}/${suffix}`;
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
    const family = String(config.widgetFamily || "medium");
    const compact = family === "small";
    const medium = family === "medium";
    const spacious = family === "large" || family === "extraLarge";
    widget.backgroundGradient = compact ? compactBgGradient(data, drift) : bgGradient(data.status_level);
    widget.url = buildOpenUrl(baseUrl);

    const statusTone = topStatusPill(data);
    const stageTone = topStagePill(data);
    const familyTone = familyBadge(family);
    addCenteredPillRow(widget, [statusTone, stageTone, familyTone]);

    widget.addSpacer(8);
    if (compact) {
      addHeroMetric(widget, driftLabel(drift.status || "-"), `残り ${drift.remaining_samples ?? "-"}`, compactHeroTone(data, drift));
    } else {
      addSummaryCard(
        widget,
        headlineText(data, drift, compact),
        medium
          ? `${resumeOutlookShort(drift)} ・ ${runnerLabel(data.runner_alive)}`
          : `bot ${runnerLabel(data.runner_alive)} ・ ${resumeOutlookShort(drift)} ・ ${stopSummary(data)}`,
        { bg: "#ffffff", title: "#0f172a", subtitle: "#475569" },
      );
    }
    widget.addSpacer(6);

    if (compact) {
      addPillRow(widget, [
        {
          text: compactStopText(data),
          ...(data.risk_stop ? { fg: "#991b1b", bg: "#fee2e2" } : data.streak_stop ? { fg: "#9a3412", bg: "#ffedd5" } : neutralPillColors()),
        },
        { text: compactResumeText(drift), ...(drift.resume_ready ? { fg: "#065f46", bg: "#d1fae5" } : neutralPillColors()) },
      ]);
      widget.addSpacer(6);
      addPillRow(widget, [
        { text: compactTradeText(data.trade_enabled), ...tradePillColors(data.trade_enabled) },
        { text: compactBotText(data.runner_alive), ...runnerPillColors(data.runner_alive) },
      ]);
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
          label: "停止",
          value: stopSummary(data),
          tone: { bg: data.risk_stop ? "#fee2e2" : data.streak_stop ? "#ffedd5" : "#e2e8f0", label: "#475569", value: data.risk_stop ? "#991b1b" : data.streak_stop ? "#9a3412" : "#334155" },
        },
        {
          label: "復帰",
          value: resumeOutlookSummary(drift),
          tone: { bg: readyPillColors(drift.resume_ready).bg, label: "#475569", value: readyPillColors(drift.resume_ready).fg },
          valueLines: 3,
        },
      ];
      if (medium) {
        infoItems.splice(1, 0, {
          label: "bot",
          value: runnerLabel(data.runner_alive),
          tone: { bg: runnerPillColors(data.runner_alive).bg, label: "#475569", value: runnerPillColors(data.runner_alive).fg },
        });
        infoItems.pop();
      }
      if (spacious) {
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
