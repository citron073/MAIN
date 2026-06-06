// Visualization primitives — donut, bars, stacked-bar, list.
// All sized to fit a parent box and accept a `width`/`height`.

const fmtMoney = (n, currency = 'USD', short = false) => {
  const value = Number(n) || 0;
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  const cur = window.OUROBOROS_CURRENCY || currency;
  if (cur === 'JPY') {
    if (short) {
      if (abs >= 1e8) return sign + '¥' + (abs / 1e8).toFixed(2) + '億';
      if (abs >= 1e4) return sign + '¥' + (abs / 1e4).toFixed(1) + '万';
      return sign + '¥' + abs.toFixed(0);
    }
    return sign + '¥' + abs.toLocaleString('ja-JP', { maximumFractionDigits: 0 });
  }
  if (short) {
    if (abs >= 1e6) return sign + '$' + (abs / 1e6).toFixed(2) + 'M';
    if (abs >= 1e3) return sign + '$' + (abs / 1e3).toFixed(2) + 'k';
    return sign + '$' + abs.toFixed(0);
  }
  return sign + '$' + abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const fmtPct = (n, digits = 2) => (n >= 0 ? '+' : '') + n.toFixed(digits) + '%';

const chartNumber = (v, fallback = 0) => {
  const x = Number(v);
  return Number.isFinite(x) ? x : fallback;
};

const positiveChartData = (data, fallbackName = 'No data') => {
  const rows = Array.isArray(data) ? data : [];
  const out = rows
    .map((d, i) => ({
      ...(d && typeof d === 'object' ? d : {}),
      name: String((d && d.name) || `${fallbackName} ${i + 1}`),
      value: Math.max(0, Math.abs(chartNumber(d && d.value, 0))),
    }))
    .filter(d => d.value > 0);
  return out.length ? out : [{ name: fallbackName, value: 1 }];
};

const finiteSeries = (data) => (Array.isArray(data) ? data.map(v => Number(v)).filter(Number.isFinite) : []);

// ─── Donut ─────────────────────────────────────────────────────────────
function Donut({ data, size = 90, thickness = 14, dark = true, accent }) {
  const rows = positiveChartData(data);
  const total = rows.reduce((s, d) => s + d.value, 0) || 1;
  const r = (size - thickness) / 2;
  const C = 2 * Math.PI * r;
  let acc = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: 'block' }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke={dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'} strokeWidth={thickness} />
      {rows.map((d, i) => {
        const frac = d.value / total;
        const len = C * frac;
        const off = -C * acc;
        acc += frac;
        const color = SECTOR_COLORS[d.name] || accent || '#888';
        return (
          <circle key={d.name} cx={size / 2} cy={size / 2} r={r} fill="none"
                  stroke={color} strokeWidth={thickness}
                  strokeDasharray={`${len} ${C - len}`} strokeDashoffset={off}
                  transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        );
      })}
    </svg>
  );
}

// ─── Stacked horizontal bar ────────────────────────────────────────────
function StackedBar({ data, width, height = 10, dark = true, radius = 4, accent }) {
  const rows = positiveChartData(data);
  const total = rows.reduce((s, d) => s + d.value, 0) || 1;
  let x = 0;
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <rect width={width} height={height} rx={radius} fill={dark ? '#222' : '#eee'} />
      <g>
        {rows.map((d, i) => {
          const w = (d.value / total) * width;
          const color = SECTOR_COLORS[d.name] || accent || '#888';
          const safeW = Math.max(0, w - 1.5);
          const rect = (
            <rect key={d.name} x={x} y={0} width={safeW} height={height}
                  fill={color} rx={i === 0 || i === rows.length - 1 ? radius : 0} />
          );
          x += w;
          return rect;
        })}
      </g>
    </svg>
  );
}

// ─── Vertical bars ─────────────────────────────────────────────────────
function VerticalBars({ data, width, height, dark = true, accent }) {
  const rows = positiveChartData(data);
  const max = Math.max(...rows.map(d => d.value), 1);
  const n = rows.length;
  const gap = 4;
  const bw = (width - gap * (n - 1)) / n;
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      {rows.map((d, i) => {
        const h = (d.value / max) * height;
        const color = SECTOR_COLORS[d.name] || accent || '#888';
        return (
          <rect key={d.name} x={i * (bw + gap)} y={height - h} width={bw} height={h}
                fill={color} rx={2} />
        );
      })}
    </svg>
  );
}

// ─── Sparkline ─────────────────────────────────────────────────────────
function Sparkline({ data, width, height, color = '#16C784', dark = true, fill = true }) {
  const rows = finiteSeries(data);
  if (rows.length < 2) {
    const y = height / 2;
    return (
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
        <path d={`M0,${y.toFixed(2)} L${width},${y.toFixed(2)}`} fill="none" stroke={dark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.18)'} strokeWidth={1.2} strokeLinecap="round" />
      </svg>
    );
  }
  const min = Math.min(...rows), max = Math.max(...rows);
  const range = max - min || 1;
  const stepX = width / (rows.length - 1);
  const pts = rows.map((v, i) => [i * stepX, height - ((v - min) / range) * (height - 2) - 1]);
  const line = pts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(2) + ',' + p[1].toFixed(2)).join(' ');
  const area = line + ` L${width},${height} L0,${height} Z`;
  const gid = 'sg' + Math.round(color.charCodeAt(1) * 7 + width);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor={color} stopOpacity={dark ? 0.32 : 0.22}/>
          <stop offset="100%" stopColor={color} stopOpacity={0}/>
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#${gid})`} />}
      <path d={line} fill="none" stroke={color} strokeWidth={1.4} strokeLinejoin="round" strokeLinecap="round"/>
    </svg>
  );
}

// ─── Compact list (top sectors with values) ────────────────────────────
function SectorList({ data, dark = true, accent, max = 5, showPct = true }) {
  const rows = positiveChartData(data);
  const total = rows.reduce((s, d) => s + d.value, 0) || 1;
  const text = dark ? '#fff' : '#000';
  const dim = dark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 10.5,
                  fontVariantNumeric: 'tabular-nums', letterSpacing: -0.1 }}>
      {rows.slice(0, max).map(d => {
        const pct = (d.value / total) * 100;
        const color = SECTOR_COLORS[d.name] || accent || '#888';
        return (
          <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 5, lineHeight: 1.2 }}>
            <span style={{ width: 6, height: 6, borderRadius: 2, background: color, flexShrink: 0 }} />
            <span style={{ color: text, flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.name}</span>
            {showPct && <span style={{ color: dim, fontFeatureSettings: '"tnum"' }}>{pct.toFixed(1)}%</span>}
          </div>
        );
      })}
    </div>
  );
}

// ─── Treemap (simple slice-and-dice) ───────────────────────────────────
function Treemap({ data, width, height, dark = true, accent }) {
  // Squarified-ish: rows of varying weight. Cheap fallback: slice-and-dice horiz.
  const rowsData = positiveChartData(data);
  const total = rowsData.reduce((s, d) => s + d.value, 0) || 1;
  const sorted = [...rowsData].sort((a, b) => b.value - a.value);

  // group into rows
  const rows = [];
  let cur = [], curSum = 0, target = total / Math.max(2, Math.round(Math.sqrt(sorted.length)));
  for (const d of sorted) {
    cur.push(d); curSum += d.value;
    if (curSum >= target * 0.95) { rows.push({ items: cur, sum: curSum }); cur = []; curSum = 0; }
  }
  if (cur.length) rows.push({ items: cur, sum: curSum });

  let y = 0;
  const out = [];
  for (const row of rows) {
    const rowH = (row.sum / total) * height;
    let x = 0;
    for (const d of row.items) {
      const w = (d.value / row.sum) * width;
      const color = SECTOR_COLORS[d.name] || accent || '#888';
      const pct = (d.value / total) * 100;
      const big = w > 38 && rowH > 26;
      out.push(
        <div key={d.name} style={{
          position: 'absolute', left: x, top: y, width: w - 1.5, height: rowH - 1.5,
          background: color, borderRadius: 3, padding: '3px 4px', boxSizing: 'border-box',
          fontSize: big ? 9.5 : 0, color: 'rgba(0,0,0,0.75)', fontWeight: 600,
          overflow: 'hidden', lineHeight: 1.1,
        }}>
          {big && <>
            <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.name}</div>
            <div style={{ opacity: 0.7, fontWeight: 500 }}>{pct.toFixed(0)}%</div>
          </>}
        </div>
      );
      x += w;
    }
    y += rowH;
  }
  return <div style={{ position: 'relative', width, height }}>{out}</div>;
}

Object.assign(window, {
  Donut, StackedBar, VerticalBars, Sparkline, SectorList, Treemap,
  fmtMoney, fmtPct,
});
