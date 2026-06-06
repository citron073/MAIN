// Alerts / notification settings sheet — iOS Settings-styled grouped list.

const DEFAULT_ALERTS = {
  dailySummary: { on: true, time: '17:00' },
  bigMover:     { on: true, upPct: 3, downPct: 3 },
  priceAlerts:  [
    { id: 'pa1', ticker: 'NVDA', op: '>',  px: 900,    on: true,  account: 'robinhood' },
    { id: 'pa2', ticker: 'BTC',  op: '>',  px: 75000,  on: true,  account: 'coinbase' },
    { id: 'pa3', ticker: 'AAPL', op: '<',  px: 195,    on: false, account: 'schwab' },
    { id: 'pa4', ticker: 'SOL',  op: '>',  px: 220,    on: true,  account: 'coinbase' },
  ],
  news:        { on: true, scope: 'holdings' },   // holdings | watchlist | all
  earnings:    { on: true, daysBefore: 2 },
  haptics:     { on: false },
  hideBalance: { on: false },
};

function AlertsSettings({ alerts, setAlerts, dark, accent, onClose }) {
  const text = dark ? '#fff' : '#0a0c12';
  const dim  = dark ? 'rgba(255,255,255,0.55)' : 'rgba(60,60,67,0.6)';
  const ter  = dark ? 'rgba(255,255,255,0.35)' : 'rgba(60,60,67,0.4)';
  const bgSheet = dark ? '#0d1014' : '#f2f2f7';
  const card = dark ? '#161618' : '#fff';
  const sep  = dark ? 'rgba(255,255,255,0.06)' : 'rgba(60,60,67,0.08)';

  const update = (path, value) => {
    setAlerts(prev => {
      const next = { ...prev };
      const parts = path.split('.');
      let cur = next;
      for (let i = 0; i < parts.length - 1; i++) {
        cur[parts[i]] = { ...cur[parts[i]] };
        cur = cur[parts[i]];
      }
      cur[parts[parts.length - 1]] = value;
      return next;
    });
  };

  const togglePriceAlert = (id) => {
    setAlerts(prev => ({
      ...prev,
      priceAlerts: prev.priceAlerts.map(p => p.id === id ? { ...p, on: !p.on } : p),
    }));
  };
  const deletePriceAlert = (id) => {
    setAlerts(prev => ({
      ...prev,
      priceAlerts: prev.priceAlerts.filter(p => p.id !== id),
    }));
  };

  return (
    <div className="pw-fade-in" onClick={onClose} style={{
      position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.45)',
      backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)',
      zIndex: 100,
    }}>
      <div className="pw-slide-up" onClick={(e) => e.stopPropagation()} style={{
        position: 'absolute', bottom: 0, left: 0, right: 0, top: 58,
        borderRadius: '24px 24px 0 0', background: bgSheet, color: text,
        overflow: 'auto', fontFamily: '-apple-system, system-ui',
      }}>
        {/* Grabber */}
        <div style={{ padding: '8px 0 4px', display: 'flex', justifyContent: 'center', position: 'relative' }}>
          <div style={{ width: 36, height: 5, borderRadius: 4, background: ter }} />
          <button onClick={onClose} style={{
            position: 'absolute', right: 14, top: 4, padding: '6px 14px', borderRadius: 999,
            background: 'transparent', border: 'none', color: accent || '#3B82F6',
            fontSize: 16, fontWeight: 600, cursor: 'pointer',
          }}>Done</button>
        </div>

        <h2 style={{
          padding: '6px 18px 0', margin: 0,
          fontSize: 28, fontWeight: 700, letterSpacing: -0.5,
        }}>Alerts</h2>
        <div style={{ padding: '4px 18px 14px', fontSize: 13, color: dim, letterSpacing: -0.1 }}>
          ポートフォリオの通知設定。プッシュ通知 / ロック画面表示の挙動を口座ごとに設定できます。
        </div>

        {/* ─── Daily Summary ─── */}
        <ListGroup header="Daily Summary" card={card} dim={dim} sep={sep}>
          <SettingsRow label="Daily summary" detail={alerts.dailySummary.on ? `Every day · ${alerts.dailySummary.time}` : 'Off'} sep={sep}
            right={<Toggle on={alerts.dailySummary.on} accent={accent} onChange={(v) => update('dailySummary.on', v)} />} />
          {alerts.dailySummary.on && (
            <SettingsRow label="Time" detail={alerts.dailySummary.time} sep={sep}
              right={<TimeSpinner value={alerts.dailySummary.time} onChange={(v) => update('dailySummary.time', v)} dark={dark} />} />
          )}
        </ListGroup>

        {/* ─── Big Movers ─── */}
        <ListGroup header="Portfolio Movers" footer="アカウント全体の損益が閾値を超えた時に通知" card={card} dim={dim} sep={sep}>
          <SettingsRow label="Threshold alerts" sep={sep}
            right={<Toggle on={alerts.bigMover.on} accent={accent} onChange={(v) => update('bigMover.on', v)} />} />
          {alerts.bigMover.on && (
            <>
              <ThresholdRow label="Up trigger" color="#16C784" value={alerts.bigMover.upPct} sep={sep}
                onChange={(v) => update('bigMover.upPct', v)} accent={accent} />
              <ThresholdRow label="Down trigger" color="#EA3943" value={alerts.bigMover.downPct} sep={sep}
                onChange={(v) => update('bigMover.downPct', v)} accent={accent} />
            </>
          )}
        </ListGroup>

        {/* ─── Price Alerts ─── */}
        <ListGroup header={`Price Alerts (${alerts.priceAlerts.filter(p => p.on).length} active)`}
          card={card} dim={dim} sep={sep}>
          {alerts.priceAlerts.map((p, i) => (
            <PriceAlertRow key={p.id}
              p={p}
              isLast={i === alerts.priceAlerts.length - 1}
              onToggle={() => togglePriceAlert(p.id)}
              onDelete={() => deletePriceAlert(p.id)}
              accent={accent} dim={dim} sep={sep} dark={dark} />
          ))}
          <SettingsRow label="+ New price alert" labelStyle={{ color: accent || '#3B82F6', fontWeight: 600 }} sep={sep}
            isLast={true} onClick={() => {
              setAlerts(prev => ({ ...prev, priceAlerts: [...prev.priceAlerts, {
                id: 'pa' + Math.random().toString(36).slice(2, 6),
                ticker: 'TSLA', op: '>', px: 200, on: true, account: 'robinhood',
              }] }));
            }} />
        </ListGroup>

        {/* ─── News / Earnings ─── */}
        <ListGroup header="News & Events" card={card} dim={dim} sep={sep}>
          <SettingsRow label="Holdings news" detail={alerts.news.on ? alerts.news.scope : 'Off'} sep={sep}
            right={<Toggle on={alerts.news.on} accent={accent} onChange={(v) => update('news.on', v)} />} />
          <SettingsRow label="Earnings reminders"
            detail={alerts.earnings.on ? `${alerts.earnings.daysBefore} day(s) before` : 'Off'} sep={sep}
            right={<Toggle on={alerts.earnings.on} accent={accent} onChange={(v) => update('earnings.on', v)} />} />
        </ListGroup>

        {/* ─── Behavior ─── */}
        <ListGroup header="Behavior" card={card} dim={dim} sep={sep}>
          <SettingsRow label="Haptic feedback on widget tap" sep={sep}
            right={<Toggle on={alerts.haptics.on} accent={accent} onChange={(v) => update('haptics.on', v)} />} />
          <SettingsRow label="Hide balance on lock screen" sep={sep} isLast
            right={<Toggle on={alerts.hideBalance.on} accent={accent} onChange={(v) => update('hideBalance.on', v)} />} />
        </ListGroup>

        <div style={{ height: 40 }} />
      </div>
    </div>
  );
}

// ─── Building blocks ───────────────────────────────────────────────────
function ListGroup({ header, footer, card, dim, sep, children }) {
  return (
    <div style={{ margin: '14px 0' }}>
      {header && <div style={{ padding: '0 32px 6px', fontSize: 12, fontWeight: 500, color: dim, letterSpacing: 0.1, textTransform: 'uppercase' }}>{header}</div>}
      <div style={{ margin: '0 16px', background: card, borderRadius: 16, overflow: 'hidden' }}>
        {children}
      </div>
      {footer && <div style={{ padding: '6px 32px 0', fontSize: 12, color: dim, letterSpacing: -0.1, lineHeight: 1.4 }}>{footer}</div>}
    </div>
  );
}

function SettingsRow({ label, labelStyle, detail, right, sep, onClick, isLast }) {
  return (
    <div onClick={onClick} style={{
      display: 'flex', alignItems: 'center', minHeight: 44, padding: '0 16px',
      borderBottom: isLast ? 'none' : `0.5px solid ${sep}`, gap: 8, cursor: onClick ? 'pointer' : 'default',
    }}>
      <span style={{ fontSize: 15, letterSpacing: -0.3, ...labelStyle }}>{label}</span>
      <div style={{ flex: 1 }} />
      {detail && <span style={{ fontSize: 14, color: 'rgba(127,127,127,0.7)', letterSpacing: -0.1, fontVariantNumeric: 'tabular-nums' }}>{detail}</span>}
      {right}
    </div>
  );
}

function Toggle({ on, accent, onChange }) {
  return (
    <button onClick={(e) => { e.stopPropagation(); onChange(!on); }} style={{
      width: 50, height: 30, borderRadius: 999, border: 'none', padding: 0, cursor: 'pointer',
      background: on ? (accent || '#34C759') : '#787880',
      position: 'relative', transition: 'background 0.2s ease',
    }}>
      <span style={{
        position: 'absolute', top: 2, left: on ? 22 : 2, width: 26, height: 26,
        borderRadius: '50%', background: '#fff',
        boxShadow: '0 2px 4px rgba(0,0,0,0.2), 0 0 1px rgba(0,0,0,0.3)',
        transition: 'left 0.18s cubic-bezier(0.2, 0.8, 0.2, 1)',
      }} />
    </button>
  );
}

function ThresholdRow({ label, color, value, onChange, sep, accent }) {
  return (
    <div style={{ padding: '10px 16px', borderBottom: `0.5px solid ${sep}` }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
          <span style={{ fontSize: 14, letterSpacing: -0.2 }}>{label}</span>
        </div>
        <span style={{
          fontSize: 14, fontVariantNumeric: 'tabular-nums', fontWeight: 700,
          color, letterSpacing: -0.2,
        }}>±{value.toFixed(1)}%</span>
      </div>
      <input type="range" min="0.5" max="10" step="0.1" value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: '100%', marginTop: 6, accentColor: color }} />
    </div>
  );
}

function TimeSpinner({ value, onChange, dark }) {
  return (
    <input type="time" value={value} onChange={(e) => onChange(e.target.value)} style={{
      background: dark ? '#2a2e3a' : '#f2f2f7', border: 'none', borderRadius: 8,
      padding: '4px 8px', fontSize: 14, color: dark ? '#fff' : '#000',
      fontFamily: 'inherit', fontVariantNumeric: 'tabular-nums',
      colorScheme: dark ? 'dark' : 'light',
    }}/>
  );
}

function PriceAlertRow({ p, onToggle, onDelete, isLast, dim, sep, accent, dark }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', padding: '10px 16px', gap: 10,
      borderBottom: isLast ? 'none' : `0.5px solid ${sep}`,
    }}>
      <div style={{
        width: 34, height: 34, borderRadius: 8,
        background: p.on ? (accent || '#3B82F6') : '#787880',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#fff', fontSize: 11, fontWeight: 700, letterSpacing: -0.2,
      }}>{p.ticker.length > 3 ? p.ticker.slice(0, 3) : p.ticker}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: -0.2 }}>{p.ticker} {p.op} ${p.px.toLocaleString()}</div>
        <div style={{ fontSize: 11, color: dim, letterSpacing: -0.1 }}>{p.account}</div>
      </div>
      <button onClick={onDelete} style={{
        width: 28, height: 28, borderRadius: '50%', border: 'none',
        background: 'rgba(234,57,67,0.15)', color: '#EA3943',
        fontSize: 16, fontWeight: 700, cursor: 'pointer',
      }}>−</button>
      <Toggle on={p.on} accent={accent} onChange={onToggle} />
    </div>
  );
}

Object.assign(window, { DEFAULT_ALERTS, AlertsSettings });
