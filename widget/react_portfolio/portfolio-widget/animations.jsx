// Tiny animation utilities — RAF-driven, no deps.

// Returns 0 → 1 over `duration` after mount.
function useEnter(duration = 700, easing) {
  const ease = easing || ((t) => 1 - Math.pow(1 - t, 3.2));
  // If the page is hidden (background tab / inactive iframe), rAF is paused,
  // so jump straight to the end state — user won't see the animation anyway.
  const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
  const [p, setP] = React.useState(hidden ? 1 : 0);
  React.useEffect(() => {
    if (hidden) return;
    let raf, t0 = null;
    const tick = (t) => {
      if (t0 === null) t0 = t;
      const frac = Math.min(1, (t - t0) / duration);
      setP(ease(frac));
      if (frac < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // Fallback: if rAF stalls (tab hidden mid-mount) snap to final state.
    const fallback = setTimeout(() => setP(1), duration + 120);
    return () => { cancelAnimationFrame(raf); clearTimeout(fallback); };
  }, []);
  return p;
}

// Tween toward `target` whenever it changes (starts from 0 on mount).
function useTween(target, duration = 700, easing) {
  const ease = easing || ((t) => 1 - Math.pow(1 - t, 3));
  const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
  // When hidden, initialise at the target so the chart isn't blank.
  const init = hidden ? +target : 0;
  const [v, setV] = React.useState(init);
  const ref = React.useRef(init);
  React.useEffect(() => {
    const end = +target;
    if (document.visibilityState === 'hidden') {
      ref.current = end; setV(end); return;
    }
    const start = ref.current;
    if (Math.abs(start - end) < 0.0001) { ref.current = end; setV(end); return; }
    const t0 = performance.now();
    let raf;
    const tick = () => {
      const elapsed = performance.now() - t0;
      const frac = Math.min(1, elapsed / duration);
      const cur = start + (end - start) * ease(frac);
      ref.current = cur; setV(cur);
      if (frac < 1) raf = requestAnimationFrame(tick);
      else ref.current = end;
    };
    raf = requestAnimationFrame(tick);
    const fallback = setTimeout(() => { ref.current = end; setV(end); }, duration + 120);
    return () => { cancelAnimationFrame(raf); clearTimeout(fallback); };
  }, [target, duration]);
  return v;
}

// Animated count-up wrapper. Renders span with formatted current value.
function AnimatedNumber({ value, format = (v) => v.toFixed(0), duration = 700, style }) {
  const v = useTween(value, duration);
  return <span style={style}>{format(v)}</span>;
}

// Animated Donut — wraps the static Donut but reveals the arcs over `duration`.
function AnimatedDonut({ data, size = 90, thickness = 14, dark = true, accent, duration = 800 }) {
  const p = useEnter(duration);
  const rows = (Array.isArray(data) ? data : [])
    .map((d, i) => ({
      ...d,
      name: String((d && d.name) || `No data ${i + 1}`),
      value: Math.max(0, Math.abs(Number(d && d.value) || 0)),
    }))
    .filter(d => d.value > 0);
  const safeRows = rows.length ? rows : [{ name: 'No data', value: 1 }];
  const total = safeRows.reduce((s, d) => s + d.value, 0) || 1;
  const r = (size - thickness) / 2;
  const C = 2 * Math.PI * r;
  let acc = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: 'block' }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke={dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'} strokeWidth={thickness} />
      {safeRows.map((d) => {
        const frac = d.value / total;
        const len = C * frac * p;
        const off = -C * acc * p;
        acc += frac;
        const color = SECTOR_COLORS[d.name] || accent || '#888';
        return (
          <circle key={d.name} cx={size / 2} cy={size / 2} r={r} fill="none"
                  stroke={color} strokeWidth={thickness}
                  strokeDasharray={`${len.toFixed(2)} ${C}`}
                  strokeDashoffset={off.toFixed(2)}
                  transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        );
      })}
    </svg>
  );
}

// Animated Sparkline — strokes-in path; area opacity fades in.
function AnimatedSparkline({ data, width, height, color = '#16C784', dark = true, duration = 900 }) {
  const p = useEnter(duration);
  const rows = Array.isArray(data) ? data.map(v => Number(v)).filter(Number.isFinite) : [];
  if (rows.length < 2) {
    const y = height / 2;
    return (
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
        <path d={`M0,${y.toFixed(2)} L${width},${y.toFixed(2)}`} fill="none" stroke={dark ? 'rgba(255,255,255,0.20)' : 'rgba(0,0,0,0.18)'} strokeWidth={1.4} strokeLinecap="round" />
      </svg>
    );
  }
  const min = Math.min(...rows), max = Math.max(...rows);
  const range = max - min || 1;
  const stepX = width / (rows.length - 1);
  const pts = rows.map((v, i) => [i * stepX, height - ((v - min) / range) * (height - 2) - 1]);
  const line = pts.map((pt, i) => (i === 0 ? 'M' : 'L') + pt[0].toFixed(2) + ',' + pt[1].toFixed(2)).join(' ');
  let pathLen = 0;
  for (let i = 1; i < pts.length; i++) pathLen += Math.hypot(pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1]);
  const area = line + ` L${width},${height} L0,${height} Z`;
  const gid = 'asg' + Math.round(color.charCodeAt(1) * 11 + width).toString(36);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor={color} stopOpacity={(dark ? 0.32 : 0.22) * p}/>
          <stop offset="100%" stopColor={color} stopOpacity={0}/>
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth={1.4}
            strokeDasharray={`${(pathLen * p).toFixed(2)} ${pathLen.toFixed(2)}`}
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// CSS keyframes mounted once globally
const AnimationStyles = () => (
  <style>{`
    @keyframes pw-slide-up {
      from { transform: translateY(100%); opacity: 0.6; }
      to   { transform: translateY(0);    opacity: 1; }
    }
    @keyframes pw-fade-in { from { opacity: 0; } to { opacity: 1; } }
    @keyframes pw-scale-in {
      from { opacity: 0; transform: scale(0.94); }
      to   { opacity: 1; transform: scale(1); }
    }
    .pw-slide-up { animation: pw-slide-up 0.36s cubic-bezier(0.2, 0.85, 0.2, 1) both; }
    .pw-fade-in  { animation: pw-fade-in 0.22s ease-out both; }
    .pw-scale-in { animation: pw-scale-in 0.28s cubic-bezier(0.2, 0.85, 0.2, 1.05) both; }
  `}</style>
);

Object.assign(window, {
  useEnter, useTween, AnimatedNumber, AnimatedDonut, AnimatedSparkline, AnimationStyles,
});
