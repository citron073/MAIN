// Widget components for iOS home screen.
// Sizes: small (2x2 / 158), medium (4x2 / 338x158), large (4x4 / 338x354),
// xl (4x6 / 338x546 — iPad style), inline (lock-screen, 1 row).
// Props: { account, dark, accent, sectorViz, plFormat, classification, w, h, onTapHolding }.

// ─── Shared chrome ─────────────────────────────────────────────────────
function WidgetSurface({ children, dark, w, h, onClick, style = {} }) {
  return (
    <div onClick={onClick} style={{
      width: w, height: h,
      borderRadius: 22,
      background: dark ? '#161618' : '#FFFFFF',
      boxShadow: dark
        ? '0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 20px rgba(0,0,0,0.35), 0 0 0 0.5px rgba(255,255,255,0.06)'
        : '0 1px 0 rgba(255,255,255,0.9) inset, 0 6px 16px rgba(15,23,42,0.10), 0 0 0 0.5px rgba(15,23,42,0.04)',
      color: dark ? '#fff' : '#0a0a0a',
      fontFamily: '-apple-system, "SF Pro Text", system-ui, sans-serif',
      WebkitFontSmoothing: 'antialiased',
      letterSpacing: -0.1,
      position: 'relative', overflow: 'hidden', cursor: 'pointer',
      ...style,
    }}>{children}</div>
  );
}

function AccountChip({ account, dark, size = 'sm' }) {
  const small = size === 'sm';
  const dim = dark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.5)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, minWidth: 0 }}>
      <div style={{
        width: small ? 14 : 18, height: small ? 14 : 18, borderRadius: 4,
        background: account.brandColor, color: '#000',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: small ? 8.5 : 10, fontWeight: 800, letterSpacing: -0.4,
        flexShrink: 0, boxShadow: '0 0 0 0.5px rgba(0,0,0,0.15) inset',
      }}>{account.short}</div>
      <div style={{
        color: dim, fontSize: small ? 10.5 : 12, fontWeight: 600,
        letterSpacing: -0.1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>{account.name}</div>
    </div>
  );
}

function PLBlock({ pl, plPct, plFormat, fontSize = 11, dark = true }) {
  const up = pl >= 0;
  const c = up ? '#16C784' : '#EA3943';
  const arrow = up ? '▲' : '▼';
  const showAbs = plFormat === 'abs' || plFormat === 'both';
  const showPct = plFormat === 'pct' || plFormat === 'both';
  return (
    <span style={{
      color: c, fontSize, fontWeight: 600, fontVariantNumeric: 'tabular-nums',
      letterSpacing: -0.15, display: 'inline-flex', alignItems: 'baseline', gap: 4,
      whiteSpace: 'nowrap',
    }}>
      <span style={{ fontSize: fontSize * 0.72 }}>{arrow}</span>
      {showAbs && <span>{fmtMoney(Math.abs(pl), 'USD', true)}</span>}
      {showAbs && showPct && <span style={{ opacity: 0.7 }}>·</span>}
      {showPct && <span>{(up ? '+' : '') + plPct.toFixed(2)}%</span>}
    </span>
  );
}

function WidgetHead({ account, dark, label, right }) {
  const dim = dark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
      <AccountChip account={account} dark={dark} />
      {right || <span style={{ color: dim, fontSize: 9.5, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase' }}>{label}</span>}
    </div>
  );
}

// Money formatter for AnimatedNumber
const fmtBig = (v) => fmtMoney(v, 'USD', true);

// Sector viz dispatcher that uses breakdown + classification
function VizArea({ kind, data, w, h, dark, accent, vKey }) {
  if (kind === 'donut') return <AnimatedDonut key={vKey} data={data} size={Math.min(w, h)} thickness={Math.min(w, h) * 0.16} dark={dark} accent={accent} />;
  if (kind === 'bars')  return <VerticalBars data={data.slice(0, 9)} width={w} height={h} dark={dark} accent={accent} />;
  if (kind === 'stack') return <StackedBar data={data} width={w} height={Math.min(h, 12)} dark={dark} accent={accent} />;
  if (kind === 'tree')  return <Treemap data={data} width={w} height={h} dark={dark} accent={accent} />;
  if (kind === 'list')  return <SectorList data={data} dark={dark} accent={accent} max={Math.floor(h / 16)} />;
  return null;
}

// ═══ SMALL 2x2 (158x158) ════════════════════════════════════════════════
function WidgetSmall({ account, dark, accent, sectorViz, plFormat, classification = 'sector', w = 158, h = 158, onClick }) {
  const breakdown = getBreakdown(account, classification);
  const vKey = account.id + ':' + classification;
  return (
    <WidgetSurface dark={dark} w={w} h={h} onClick={onClick}>
      <div style={{ padding: 12, height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
        <WidgetHead account={account} dark={dark} label="TODAY" />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', marginTop: 4 }}>
          <div style={{
            fontSize: 21, fontWeight: 700, letterSpacing: -0.6,
            fontVariantNumeric: 'tabular-nums', lineHeight: 1.1,
          }}><AnimatedNumber value={account.value} format={fmtBig} duration={700}/></div>
          <div style={{ marginTop: 3 }}>
            <PLBlock pl={account.todayPL} plPct={account.todayPLPct} plFormat={plFormat} fontSize={11} dark={dark} />
          </div>
        </div>
        <div style={{ marginTop: 6 }}>
          {sectorViz === 'donut'
            ? <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <AnimatedDonut key={vKey} data={breakdown} size={42} thickness={7} dark={dark} accent={accent} />
                <SectorList data={breakdown} max={3} dark={dark} accent={accent} />
              </div>
            : sectorViz === 'list'
            ? <SectorList data={breakdown} max={3} dark={dark} accent={accent} />
            : <VizArea kind={sectorViz} data={breakdown} w={w - 24} h={28} dark={dark} accent={accent} vKey={vKey} />
          }
        </div>
      </div>
    </WidgetSurface>
  );
}

// ═══ MEDIUM 4x2 (338x158) ═══════════════════════════════════════════════
function WidgetMedium({ account, dark, accent, sectorViz, plFormat, classification = 'sector', w = 338, h = 158, onClick }) {
  const breakdown = getBreakdown(account, classification);
  const vKey = account.id + ':' + classification;
  const dim = dark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)';
  const sepC = dark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.06)';
  const up = account.todayPL >= 0;
  return (
    <WidgetSurface dark={dark} w={w} h={h} onClick={onClick}>
      <div style={{ padding: 14, height: '100%', display: 'flex', boxSizing: 'border-box', gap: 12 }}>
        {/* LEFT */}
        <div style={{ flex: 1.15, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <WidgetHead account={account} dark={dark} label="PORTFOLIO" />
          <div style={{ marginTop: 6 }}>
            <div style={{
              fontSize: 26, fontWeight: 700, letterSpacing: -0.8,
              fontVariantNumeric: 'tabular-nums', lineHeight: 1,
            }}><AnimatedNumber value={account.value} format={fmtBig} duration={700}/></div>
            <div style={{ marginTop: 4 }}>
              <PLBlock pl={account.todayPL} plPct={account.todayPLPct} plFormat={plFormat} fontSize={12} dark={dark} />
            </div>
          </div>
          <div style={{ flex: 1, marginTop: 6, display: 'flex', alignItems: 'flex-end' }}>
            <AnimatedSparkline key={account.id + ':sp'} data={account.sparkline} width={150} height={28}
              color={up ? '#16C784' : '#EA3943'} dark={dark} />
          </div>
        </div>
        <div style={{ width: 0.5, background: sepC }} />
        {/* RIGHT */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ color: dim, fontSize: 9.5, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase' }}>{classificationTitle(classification)}</div>
          <div style={{ flex: 1, marginTop: 6, display: 'flex', gap: 8, alignItems: 'center' }}>
            {sectorViz === 'donut' && (
              <>
                <AnimatedDonut key={vKey} data={breakdown} size={70} thickness={11} dark={dark} accent={accent} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <SectorList data={breakdown} max={4} dark={dark} accent={accent} />
                </div>
              </>
            )}
            {sectorViz === 'bars'  && <VerticalBars data={breakdown.slice(0, 8)} width={140} height={72} dark={dark} accent={accent} />}
            {sectorViz === 'stack' && (
              <div style={{ width: '100%' }}>
                <StackedBar data={breakdown} width={140} height={10} dark={dark} accent={accent} />
                <div style={{ marginTop: 8 }}>
                  <SectorList data={breakdown} max={3} dark={dark} accent={accent} />
                </div>
              </div>
            )}
            {sectorViz === 'tree' && <Treemap data={breakdown} width={140} height={80} dark={dark} accent={accent} />}
            {sectorViz === 'list' && <SectorList data={breakdown} max={5} dark={dark} accent={accent} />}
          </div>
        </div>
      </div>
    </WidgetSurface>
  );
}

// ═══ LARGE 4x4 (338x354) ════════════════════════════════════════════════
function WidgetLarge({ account, dark, accent, sectorViz, plFormat, classification = 'sector', w = 338, h = 354, onClick }) {
  const breakdown = getBreakdown(account, classification);
  const vKey = account.id + ':' + classification;
  const dim = dark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)';
  const ter = dark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)';
  const sepC = dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
  const up = account.todayPL >= 0;
  const upC = '#16C784', dnC = '#EA3943';
  const total = breakdown.reduce((s, d) => s + d.value, 0);

  return (
    <WidgetSurface dark={dark} w={w} h={h} onClick={onClick}>
      <div style={{ padding: 16, height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box', gap: 12 }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <AccountChip account={account} dark={dark} size="md" />
            <div style={{ color: dim, fontSize: 10, marginTop: 2, marginLeft: 23 }}>{account.type}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: ter, fontSize: 9.5, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase' }}>Today · 14:23</div>
            <div style={{ color: dim, fontSize: 10, marginTop: 2, fontVariantNumeric: 'tabular-nums' }}>
              S&P <span style={{ color: '#16C784' }}>+0.42%</span>  ·  BTC <span style={{ color: '#16C784' }}>+1.18%</span>
            </div>
          </div>
        </div>

        {/* Hero */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12 }}>
          <div>
            <div style={{
              fontSize: 34, fontWeight: 700, letterSpacing: -1,
              fontVariantNumeric: 'tabular-nums', lineHeight: 1,
            }}><AnimatedNumber value={account.value} format={fmtBig} duration={750}/></div>
            <div style={{ marginTop: 6 }}>
              <PLBlock pl={account.todayPL} plPct={account.todayPLPct} plFormat={plFormat} fontSize={13} dark={dark} />
            </div>
          </div>
          <AnimatedSparkline key={account.id + ':sp'} data={account.sparkline} width={120} height={42}
            color={up ? upC : dnC} dark={dark} />
        </div>

        {/* Quick stats */}
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 1,
          background: sepC, borderRadius: 8, overflow: 'hidden',
        }}>
          {[
            { label: 'WEEK', val: account.weekPLPct },
            { label: 'YTD',  val: account.ytdPLPct },
            { label: 'CASH', val: account.cash, isMoney: true },
          ].map(s => (
            <div key={s.label} style={{ background: dark ? '#161618' : '#fff', padding: '6px 8px' }}>
              <div style={{ color: ter, fontSize: 8.5, fontWeight: 600, letterSpacing: 0.4 }}>{s.label}</div>
              <div style={{
                fontSize: 12, fontWeight: 600, marginTop: 1,
                fontVariantNumeric: 'tabular-nums', letterSpacing: -0.2,
                color: s.isMoney ? (dark ? '#fff' : '#000') : (s.val >= 0 ? upC : dnC),
              }}>{s.isMoney ? fmtMoney(s.val, 'USD', true) : fmtPct(s.val, 2)}</div>
            </div>
          ))}
        </div>

        {/* Sector viz */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ color: ter, fontSize: 9.5, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase' }}>{classificationTitle(classification)} Allocation</div>
            <div style={{ color: ter, fontSize: 9.5, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase' }}>{breakdown.length} groups</div>
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            {sectorViz === 'donut' && (
              <>
                <div style={{ position: 'relative' }}>
                  <AnimatedDonut key={vKey} data={breakdown} size={96} thickness={14} dark={dark} accent={accent} />
                  <div style={{
                    position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center', lineHeight: 1.1,
                  }}>
                    <div style={{ color: ter, fontSize: 8, fontWeight: 600, letterSpacing: 0.3 }}>TOP</div>
                    <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: -0.2 }}>{breakdown[0].name}</div>
                    <div style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums', color: dim }}>
                      {((breakdown[0].value / total) * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <SectorList data={breakdown} max={6} dark={dark} accent={accent} />
                </div>
              </>
            )}
            {sectorViz === 'bars'  && <VerticalBars data={breakdown.slice(0, 9)} width={w - 32} height={96} dark={dark} accent={accent} />}
            {sectorViz === 'stack' && (
              <div style={{ width: '100%' }}>
                <StackedBar data={breakdown} width={w - 32} height={14} dark={dark} accent={accent} />
                <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                  <SectorList data={breakdown.slice(0, 4)} max={4} dark={dark} accent={accent} />
                  <SectorList data={breakdown.slice(4, 8)} max={4} dark={dark} accent={accent} />
                </div>
              </div>
            )}
            {sectorViz === 'tree' && <Treemap data={breakdown} width={w - 32} height={96} dark={dark} accent={accent} />}
            {sectorViz === 'list' && <SectorList data={breakdown} max={6} dark={dark} accent={accent} />}
          </div>
        </div>
      </div>
    </WidgetSurface>
  );
}

// ═══ EXTRA-LARGE 4x6 — adds tappable holdings list ══════════════════════
function WidgetXL({ account, dark, accent, sectorViz, plFormat, classification = 'sector', w = 338, h = 546, onClick, onTapHolding }) {
  const dim = dark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)';
  const ter = dark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)';
  const sepC = dark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.06)';
  return (
    <WidgetSurface dark={dark} w={w} h={h} onClick={onClick}>
      <div style={{ padding: 0, height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
        <div style={{ flexShrink: 0 }}>
          <WidgetLarge account={account} dark={dark} accent={accent} sectorViz={sectorViz} plFormat={plFormat} classification={classification} w={w} h={354} />
        </div>
        <div style={{ flex: 1, padding: '4px 16px 16px', display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0' }}>
            <div style={{ color: ter, fontSize: 9.5, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase' }}>Top Holdings</div>
            <div style={{ color: ter, fontSize: 9.5, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase' }}>Wt · Today · Tap →</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0, flex: 1, minHeight: 0, overflow: 'hidden' }}>
            {account.holdings.slice(0, 7).map((h, i) => (
              <div key={h.ticker}
                   onClick={(e) => { if (onTapHolding) { e.stopPropagation(); onTapHolding(h, account); } }}
                   style={{
                     display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0',
                     borderTop: i === 0 ? 'none' : `0.5px solid ${sepC}`,
                     fontSize: 11, fontVariantNumeric: 'tabular-nums', letterSpacing: -0.1,
                     cursor: 'pointer',
                   }}>
                <span style={{ fontWeight: 700, width: 46 }}>{h.ticker}</span>
                <span style={{ flex: 1, color: dim, fontSize: 10.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.name}</span>
                <span style={{ color: dim, fontVariantNumeric: 'tabular-nums', width: 36, textAlign: 'right' }}>{h.w.toFixed(1)}%</span>
                <span style={{
                  width: 50, textAlign: 'right', fontWeight: 600,
                  color: h.plPct >= 0 ? '#16C784' : '#EA3943',
                }}>{fmtPct(h.plPct, 2)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </WidgetSurface>
  );
}

// ═══ LOCK-SCREEN INLINE ═══════════════════════════════════════════════════
function WidgetInline({ account, dark = true, plFormat = 'pct' }) {
  const up = account.todayPL >= 0;
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '2px 10px',
      borderRadius: 999, background: 'rgba(255,255,255,0.18)',
      backdropFilter: 'blur(20px)', WebkitBackdropFilter: 'blur(20px)',
      color: '#fff', fontSize: 13, fontWeight: 600, letterSpacing: -0.2,
      fontFamily: '-apple-system, system-ui',
    }}>
      <span style={{ fontSize: 10, opacity: 0.85 }}>$</span>
      <span style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtMoney(account.value, 'USD', true).replace('$', '')}</span>
      <span style={{ opacity: 0.45 }}>·</span>
      <span style={{
        color: up ? '#5DFFA6' : '#FF8E94', fontVariantNumeric: 'tabular-nums',
      }}>{(up ? '+' : '') + account.todayPLPct.toFixed(2)}%</span>
    </div>
  );
}

function WidgetCircular({ account, dark = true }) {
  const up = account.todayPL >= 0;
  const size = 72;
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: 'rgba(255,255,255,0.15)',
      backdropFilter: 'blur(20px)', WebkitBackdropFilter: 'blur(20px)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      color: '#fff', fontFamily: '-apple-system, system-ui',
      position: 'relative', overflow: 'hidden',
      boxShadow: 'inset 0 0 0 0.5px rgba(255,255,255,0.2)',
    }}>
      <div style={{ position: 'absolute', inset: 4 }}>
        <AnimatedDonut data={account.sectors} size={size - 8} thickness={3} dark accent="#fff" />
      </div>
      <div style={{ fontSize: 9, opacity: 0.7, fontWeight: 600, letterSpacing: 0.3 }}>{account.short}</div>
      <div style={{
        fontSize: 14, fontWeight: 700, letterSpacing: -0.4,
        fontVariantNumeric: 'tabular-nums', lineHeight: 1,
      }}>{fmtMoney(account.value, 'USD', true).replace('$', '')}</div>
      <div style={{
        fontSize: 9, fontWeight: 600, marginTop: 1,
        color: up ? '#5DFFA6' : '#FF8E94', fontVariantNumeric: 'tabular-nums',
      }}>{(up ? '+' : '') + account.todayPLPct.toFixed(1)}%</div>
    </div>
  );
}

Object.assign(window, {
  WidgetSurface, AccountChip, PLBlock, WidgetHead,
  WidgetSmall, WidgetMedium, WidgetLarge, WidgetXL, WidgetInline, WidgetCircular,
});
