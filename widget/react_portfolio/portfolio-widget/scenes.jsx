// Lock screen + StandBy scenes — alternate contexts for the widget.

function LockScreen({ accounts, dark, accent }) {
  const allAcct = aggregateAccounts(accounts);
  const sub = 'rgba(255,255,255,0.7)';
  return (
    <div style={{
      width: 402, height: 874, position: 'relative', overflow: 'hidden',
      background: `radial-gradient(120% 80% at 50% 110%, #2a3464 0%, #131933 45%, #06070d 90%)`,
      borderRadius: 48, fontFamily: '-apple-system, system-ui', color: '#fff',
    }}>
      {/* Dynamic Island */}
      <div style={{
        position: 'absolute', top: 11, left: '50%', transform: 'translateX(-50%)',
        width: 126, height: 37, borderRadius: 24, background: '#000', zIndex: 50,
      }} />

      {/* Date / time block */}
      <div style={{ position: 'absolute', top: 56, left: 0, right: 0, textAlign: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: 0.1, color: sub }}>Tuesday, May 13</div>
        <div style={{ fontSize: 96, fontWeight: 200, letterSpacing: -3, lineHeight: 1, marginTop: -2 }}>9:41</div>
      </div>

      {/* Inline widget (above time) */}
      <div style={{ position: 'absolute', top: 162, left: 0, right: 0, display: 'flex', justifyContent: 'center' }}>
        <WidgetInline account={allAcct} />
      </div>

      {/* Circular widgets row */}
      <div style={{
        position: 'absolute', top: 220, left: 0, right: 0,
        display: 'flex', justifyContent: 'center', gap: 14,
      }}>
        {accounts.slice(0, 4).map(a => (
          <WidgetCircular key={a.id} account={a} />
        ))}
      </div>

      {/* Decorative notifications */}
      <div style={{
        position: 'absolute', bottom: 130, left: 12, right: 12,
        display: 'flex', flexDirection: 'column', gap: 8,
      }}>
        {[
          { app: 'Bloomberg', body: 'NVDA +3.2% — earnings beat consensus by 8.4%', t: '5m' },
          { app: 'Coinbase',  body: 'BTC crossed $72,000 · alert from your watchlist', t: '12m' },
        ].map((n, i) => (
          <div key={i} style={{
            padding: '10px 14px', borderRadius: 18,
            background: 'rgba(255,255,255,0.16)',
            backdropFilter: 'blur(20px) saturate(180%)', WebkitBackdropFilter: 'blur(20px) saturate(180%)',
            boxShadow: 'inset 0 0.5px 0 rgba(255,255,255,0.2)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, opacity: 0.7 }}>
              <span style={{ fontWeight: 600 }}>{n.app}</span><span>{n.t} ago</span>
            </div>
            <div style={{ fontSize: 13, marginTop: 2 }}>{n.body}</div>
          </div>
        ))}
      </div>

      {/* Flashlight / camera glass buttons */}
      <div style={{ position: 'absolute', bottom: 56, left: 30, width: 44, height: 44, borderRadius: '50%',
        background: 'rgba(255,255,255,0.16)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        backdropFilter: 'blur(20px)' }}>🔦</div>
      <div style={{ position: 'absolute', bottom: 56, right: 30, width: 44, height: 44, borderRadius: '50%',
        background: 'rgba(255,255,255,0.16)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        backdropFilter: 'blur(20px)' }}>📷</div>

      {/* Home indicator */}
      <div style={{ position: 'absolute', bottom: 8, left: 0, right: 0, display: 'flex', justifyContent: 'center' }}>
        <div style={{ width: 139, height: 5, borderRadius: 100, background: 'rgba(255,255,255,0.7)' }} />
      </div>
    </div>
  );
}

// StandBy mode — large clock-like widget when phone is on its side, charging
function StandByScene({ accounts, dark, accent, sectorViz, plFormat }) {
  const allAcct = aggregateAccounts(accounts);
  // landscape — width > height
  return (
    <div style={{
      width: 874, height: 402, position: 'relative', overflow: 'hidden',
      background: '#000', borderRadius: 48, fontFamily: '-apple-system, system-ui', color: '#fff',
      display: 'flex', padding: '36px 56px', boxSizing: 'border-box', gap: 36, alignItems: 'center',
    }}>
      {/* Time */}
      <div style={{ flexShrink: 0 }}>
        <div style={{ fontSize: 18, fontWeight: 500, color: 'rgba(255,255,255,0.6)' }}>Tuesday, May 13</div>
        <div style={{
          fontSize: 220, fontWeight: 200, letterSpacing: -8, lineHeight: 0.9,
          color: accent || '#ff6b3b',
          fontFamily: 'ui-rounded, -apple-system, system-ui',
        }}>9:41</div>
      </div>
      {/* Portfolio standby widget — info dense */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', height: '100%' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 13, color: 'rgba(255,255,255,0.55)', letterSpacing: 0.3, textTransform: 'uppercase', fontWeight: 600 }}>Portfolio · All Accounts</span>
          </div>
          <div style={{
            fontSize: 64, fontWeight: 700, letterSpacing: -2, fontVariantNumeric: 'tabular-nums', lineHeight: 1,
            marginTop: 6,
          }}>{fmtMoney(allAcct.value, 'USD', true)}</div>
          <div style={{ marginTop: 8 }}>
            <PLBlock pl={allAcct.todayPL} plPct={allAcct.todayPLPct} plFormat={plFormat || 'both'} fontSize={20} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <Donut data={allAcct.sectors} size={86} thickness={12} dark accent={accent} />
          <div style={{ flex: 1 }}>
            <SectorList data={allAcct.sectors} max={5} dark accent={accent} />
          </div>
          <Sparkline data={allAcct.sparkline} width={180} height={64} color="#16C784" />
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { LockScreen, StandByScene });
