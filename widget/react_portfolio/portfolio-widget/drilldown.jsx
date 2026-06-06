// Stock drilldown — full-screen detail sheet inside the iPhone frame.

const STOCK_DETAIL = {
  NVDA: {
    price: 887.42, dayChg: 24.30, dayChgPct: 2.81,
    volume: '42.1M', mktCap: '$2.18T', pe: 65.4, eps: 13.55, divY: 0.02,
    range52w: [397.50, 974.00], beta: 1.74,
    description: 'GPU + accelerated computing leader; ~88% data-center revenue.',
    news: [
      { title: 'NVIDIA Q1 beats; raises Q2 guidance ~12%',  src: 'Bloomberg', t: '2h' },
      { title: 'Hyperscaler capex commitments hit $200B+',  src: 'Reuters',   t: '5h' },
      { title: 'Analyst lifts NVDA target to $1,200',       src: 'CNBC',      t: '1d' },
    ],
  },
  AAPL: {
    price: 211.18, dayChg: 0.89, dayChgPct: 0.42,
    volume: '38.5M', mktCap: '$3.21T', pe: 32.1, eps: 6.57, divY: 0.45,
    range52w: [164.08, 220.20], beta: 1.18,
    description: 'Consumer hardware + services; iPhone, Mac, App Store, ad-tier services.',
    news: [
      { title: 'WWDC preview: on-device AI tooling expected', src: 'The Verge', t: '4h' },
      { title: 'Services revenue tops $24B in latest quarter', src: 'WSJ',      t: '1d' },
      { title: 'Vision Pro shipments tracked 1.4M YTD',        src: 'IDC',      t: '2d' },
    ],
  },
  BTC: {
    price: 72845.10, dayChg: 1305.40, dayChgPct: 1.84,
    volume: '$32.4B', mktCap: '$1.44T', pe: null, eps: null, divY: null,
    range52w: [38420, 73850], beta: null,
    description: 'Reserve crypto asset; halving cycle bull pattern intact.',
    news: [
      { title: 'Spot ETF inflows top $480M for the week',   src: 'Coindesk', t: '3h' },
      { title: 'Miner reserves at 18-month lows',           src: 'Glassnode',t: '6h' },
      { title: 'Macro: DXY weakens, risk-on bid for BTC',    src: 'FT',      t: '1d' },
    ],
  },
  ETH: {
    price: 3942.18, dayChg: 113.50, dayChgPct: 2.95,
    volume: '$14.2B', mktCap: '$473B', pe: null, eps: null, divY: null,
    range52w: [1880, 4080], beta: null,
    description: 'Smart-contract L1; staking yield ~3.1%; ETF approval pending.',
    news: [
      { title: 'L2 fees down 78% post-Dencun',              src: 'Coindesk', t: '5h' },
      { title: 'Staking ratio hits 27% of supply',          src: 'Glassnode',t: '1d' },
      { title: 'ETH/BTC ratio reclaims 0.055',              src: 'TradingView', t: '1d' },
    ],
  },
};

// Generate deterministic-looking detail for tickers without explicit data.
function fakeDetail(h, account) {
  const ticker = h.ticker;
  const dayPct = h.plPct;
  const isCrypto = account.type.includes('Crypto');
  const seed = ticker.charCodeAt(0) + ticker.length;
  const price = isCrypto ? (5 + (seed % 50) * 12) : (50 + (seed % 800));
  const dayChg = price * dayPct / 100;
  const r52L = price * (0.55 + (seed % 7) * 0.04);
  const r52H = price * (1.05 + (seed % 5) * 0.06);
  return {
    price, dayChg, dayChgPct: dayPct,
    volume: isCrypto ? `$${(seed * 0.7).toFixed(1)}M` : `${(seed * 0.42).toFixed(1)}M`,
    mktCap: isCrypto ? `$${(seed * 0.18).toFixed(2)}B` : `$${(seed * 4.2).toFixed(1)}B`,
    pe: isCrypto ? null : 12 + (seed % 32),
    eps: isCrypto ? null : (price / (12 + (seed % 32))).toFixed(2),
    divY: isCrypto ? null : ((seed % 30) * 0.05).toFixed(2),
    range52w: [r52L, r52H],
    beta: isCrypto ? null : (0.6 + (seed % 12) * 0.12).toFixed(2),
    description: isCrypto ? `${h.name} — crypto position in ${account.name}.` : `${h.name} — equity holding.`,
    news: [
      { title: `${ticker} positioning rotation watched by funds`, src: 'Bloomberg', t: `${(seed % 6) + 1}h` },
      { title: `${h.name} sector breadth holding firm`,           src: 'Reuters',   t: `${(seed % 5) + 2}h` },
      { title: `Sell-side updates ${ticker} estimates`,           src: 'CNBC',      t: '1d' },
    ],
  };
}

function StockDetail({ holding, account, dark, accent, plFormat, onClose }) {
  const d = STOCK_DETAIL[holding.ticker] || fakeDetail(holding, account);
  const up = d.dayChg >= 0;
  const upC = '#16C784', dnC = '#EA3943';
  const PLc = up ? upC : dnC;

  // Build a fake intraday sparkline based on the symbol
  const seed = holding.ticker.charCodeAt(0) * 13 + holding.ticker.length * 7;
  const intraday = React.useMemo(() => spark(seed, 78, 0.006, up ? 0.0006 : -0.0005), [seed, up]);

  const text = dark ? '#fff' : '#0a0c12';
  const dim  = dark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)';
  const ter  = dark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)';
  const card = dark ? '#161618' : '#fff';
  const sep  = dark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.07)';

  const shares = (holding.value / d.price).toFixed(d.price < 10 ? 2 : 4);
  const avgCost = d.price * (1 - (holding.plPct / 100) * 0.6);   // ad-hoc derivation
  const unrealized = (d.price - avgCost) * (holding.value / d.price);
  const unrealizedPct = ((d.price - avgCost) / avgCost) * 100;

  // 52w range slider position
  const rangePos = Math.max(0, Math.min(1, (d.price - d.range52w[0]) / (d.range52w[1] - d.range52w[0])));

  return (
    <div className="pw-fade-in" onClick={onClose} style={{
      position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)',
      backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)',
      zIndex: 100,
    }}>
      <div className="pw-slide-up" onClick={(e) => e.stopPropagation()} style={{
        position: 'absolute', bottom: 0, left: 0, right: 0,
        top: 58,
        borderRadius: '24px 24px 0 0', background: dark ? '#0d1014' : '#f2f2f7',
        color: text, fontFamily: '-apple-system, system-ui',
        overflow: 'auto', display: 'flex', flexDirection: 'column',
      }}>
        {/* Grabber + close */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '8px 0 4px', position: 'relative' }}>
          <div style={{ width: 36, height: 5, borderRadius: 4, background: ter }} />
          <button onClick={onClose} style={{
            position: 'absolute', right: 14, top: 8, width: 30, height: 30, borderRadius: '50%',
            background: dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)', border: 'none',
            color: text, fontSize: 14, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600,
          }}>✕</button>
        </div>

        {/* Header */}
        <div style={{ padding: '6px 18px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.4 }}>{holding.ticker}</span>
            <span style={{ fontSize: 13, color: dim }}>{holding.name}</span>
            <div style={{ flex: 1 }} />
            <AccountChip account={account} dark={dark} size="sm" />
          </div>

          <div style={{ marginTop: 10, display: 'flex', alignItems: 'flex-end', gap: 10 }}>
            <span style={{
              fontSize: 38, fontWeight: 700, letterSpacing: -1, lineHeight: 1,
              fontVariantNumeric: 'tabular-nums',
            }}>${d.price.toLocaleString('en-US', { maximumFractionDigits: d.price < 10 ? 4 : 2 })}</span>
            <PLBlock pl={d.dayChg * (holding.value / d.price) / 1} plPct={d.dayChgPct} plFormat={plFormat} fontSize={14} dark={dark} />
          </div>
          <div style={{ fontSize: 11, color: ter, marginTop: 3, letterSpacing: 0.3, fontVariantNumeric: 'tabular-nums' }}>
            14:23 ET · NASDAQ · vol {d.volume}
          </div>
        </div>

        {/* Intraday chart */}
        <div style={{ padding: '14px 18px 6px' }}>
          <AnimatedSparkline data={intraday} width={350} height={100} color={PLc} dark={dark} duration={1100}/>
          <div style={{
            display: 'flex', justifyContent: 'space-between', marginTop: 4,
            color: ter, fontSize: 9.5, letterSpacing: 0.4, textTransform: 'uppercase', fontWeight: 600,
          }}>
            <span>9:30</span><span>11:00</span><span>12:30</span><span>14:00</span><span>16:00</span>
          </div>
        </div>

        {/* Period tabs */}
        <div style={{ padding: '6px 18px 14px' }}>
          <div style={{
            display: 'flex', gap: 4, background: dark ? '#161821' : '#e5e6ec',
            padding: 3, borderRadius: 10,
          }}>
            {['1D', '1W', '1M', '3M', '1Y', '5Y', 'ALL'].map((p, i) => (
              <div key={p} style={{
                flex: 1, textAlign: 'center', padding: '5px 0', borderRadius: 8,
                background: i === 0 ? (dark ? '#2a2e3e' : '#fff') : 'transparent',
                color: i === 0 ? text : dim,
                fontSize: 11, fontWeight: 600, cursor: 'pointer',
                boxShadow: i === 0 ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
              }}>{p}</div>
            ))}
          </div>
        </div>

        {/* Position card */}
        <div style={{
          margin: '0 14px 14px', padding: 14, background: card, borderRadius: 16,
          display: 'flex', flexDirection: 'column', gap: 10,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.3, color: dim, textTransform: 'uppercase' }}>Your Position</span>
            <span style={{
              fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999,
              background: unrealizedPct >= 0 ? 'rgba(22,199,132,0.15)' : 'rgba(234,57,67,0.15)',
              color: unrealizedPct >= 0 ? upC : dnC,
              fontVariantNumeric: 'tabular-nums',
            }}>{unrealizedPct >= 0 ? '+' : ''}{unrealizedPct.toFixed(2)}% unrealized</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, fontVariantNumeric: 'tabular-nums' }}>
            <PositionCell label="Shares"      value={shares} dim={dim} />
            <PositionCell label="Avg Cost"    value={'$' + avgCost.toFixed(2)} dim={dim} />
            <PositionCell label="Market Val"  value={fmtMoney(holding.value, 'USD', true)} dim={dim} />
            <PositionCell label="Unrealized"  value={fmtMoney(unrealized, 'USD', true)} dim={dim} color={unrealizedPct >= 0 ? upC : dnC} />
            <PositionCell label="Weight"      value={holding.w.toFixed(2) + '%'} dim={dim} />
            <PositionCell label="Day P/L"     value={fmtPct(d.dayChgPct, 2)} dim={dim} color={PLc} />
          </div>
        </div>

        {/* Key stats */}
        <div style={{
          margin: '0 14px 14px', padding: '4px 14px', background: card, borderRadius: 16,
        }}>
          <div style={{ padding: '10px 0 8px', fontSize: 12, fontWeight: 700, letterSpacing: 0.3, color: dim, textTransform: 'uppercase' }}>Key Stats</div>
          <StatRow label="Market Cap" value={d.mktCap} sep={sep} />
          <StatRow label="P/E" value={d.pe ?? '—'} sep={sep} />
          <StatRow label="EPS (TTM)" value={d.eps ?? '—'} sep={sep} />
          <StatRow label="Div Yield" value={d.divY != null ? d.divY + '%' : '—'} sep={sep} />
          <StatRow label="Beta" value={d.beta ?? '—'} sep={sep} />
          <StatRow label="Volume" value={d.volume} sep={sep} />
          <div style={{ padding: '12px 0 10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: dim, fontVariantNumeric: 'tabular-nums' }}>
              <span>52W Low ${d.range52w[0].toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
              <span>52W High ${d.range52w[1].toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
            </div>
            <div style={{ marginTop: 4, position: 'relative', height: 6, borderRadius: 3, background: sep }}>
              <div style={{
                position: 'absolute', top: -3, left: `${rangePos * 100}%`, width: 12, height: 12,
                marginLeft: -6, borderRadius: '50%', background: PLc,
                boxShadow: '0 0 0 2px ' + card, border: '1px solid rgba(0,0,0,0.1)',
              }} />
            </div>
          </div>
        </div>

        {/* News */}
        <div style={{ margin: '0 14px 14px' }}>
          <div style={{ padding: '4px 4px 8px', fontSize: 12, fontWeight: 700, letterSpacing: 0.3, color: dim, textTransform: 'uppercase' }}>News</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {d.news.map((n, i) => (
              <div key={i} style={{
                background: card, padding: 12, borderRadius: 14,
                display: 'flex', flexDirection: 'column', gap: 4,
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, letterSpacing: -0.2, lineHeight: 1.3 }}>{n.title}</div>
                <div style={{ fontSize: 11, color: dim, letterSpacing: 0.2 }}>{n.src} · {n.t} ago</div>
              </div>
            ))}
          </div>
        </div>

        {/* Action buttons */}
        <div style={{ margin: '0 14px 28px', display: 'flex', gap: 10 }}>
          <button style={{
            flex: 1, height: 44, borderRadius: 14, border: 'none',
            background: upC, color: '#000', fontWeight: 700, fontSize: 15, cursor: 'pointer',
          }}>Buy</button>
          <button style={{
            flex: 1, height: 44, borderRadius: 14, border: 'none',
            background: dnC, color: '#000', fontWeight: 700, fontSize: 15, cursor: 'pointer',
          }}>Sell</button>
          <button style={{
            width: 44, height: 44, borderRadius: 14, border: '1px solid ' + sep,
            background: card, color: text, fontSize: 18, cursor: 'pointer',
          }}>🔔</button>
        </div>
      </div>
    </div>
  );
}

function PositionCell({ label, value, dim, color }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: dim, letterSpacing: 0.3, textTransform: 'uppercase', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, letterSpacing: -0.2, marginTop: 2, color: color || 'inherit' }}>{value}</div>
    </div>
  );
}

function StatRow({ label, value, sep }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', padding: '9px 0',
      borderTop: `0.5px solid ${sep}`, fontSize: 13,
    }}>
      <span style={{ opacity: 0.65 }}>{label}</span>
      <span style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  );
}

Object.assign(window, { StockDetail });
