// Main app — orchestrates state, tweaks, scene toggle, modals.

const DEFAULT_LAYOUT = [
  { id: 'w1', size: 'medium', accountId: 'all' },
  { id: 'w2', size: 'small',  accountId: 'robinhood' },
  { id: 'w3', size: 'small',  accountId: 'coinbase' },
  { id: 'w4', size: 'large',  accountId: 'schwab' },
  { id: 'w5', size: 'small',  accountId: 'binance' },
];

const TWEAKS = /*EDITMODE-BEGIN*/{
  "dark": true,
  "accent": "#FF6B3B",
  "sectorViz": "donut",
  "plFormat": "both",
  "classification": "sector",
  "scene": "overview",
  "showGallery": true
}/*EDITMODE-END*/;

const ACCENT_OPTIONS = ['#FF6B3B', '#3B82F6', '#16C784', '#9945FF', '#E94560', '#F7B500'];
const SECTOR_VIZ_OPTIONS = ['donut', 'bars', 'stack', 'tree', 'list'];
const PL_FORMAT_OPTIONS = ['abs', 'pct', 'both'];
const CLASSIFICATION_OPTIONS = ['sector', 'industry', 'region', 'asset'];
const SCENE_OPTIONS = ['overview', 'reflection', 'history', 'home', 'lock', 'standby'];
const SCENE_LABELS = { overview: 'Overview', reflection: 'Reflection', history: 'Trades', home: 'Home', lock: 'Lock', standby: 'StandBy' };
const SWITCHER_SCENES = ['overview', 'reflection', 'history', 'home'];

function sceneFromQuery() {
  try {
    const scene = new URLSearchParams(window.location.search).get('scene');
    return SCENE_OPTIONS.includes(scene) ? scene : null;
  } catch {
    return null;
  }
}

function queryFlag(name) {
  try {
    const value = new URLSearchParams(window.location.search).get(name);
    return value === '1' || value === 'true' || value === 'yes';
  } catch {
    return false;
  }
}

function App() {
  const [t, setTweak] = useTweaks(TWEAKS);
  const [widgets, setWidgets] = React.useState(DEFAULT_LAYOUT);
  const [editing, setEditing] = React.useState(false);
  const [focusAccount, setFocusAccount] = React.useState('all');
  const [alerts, setAlerts] = React.useState(DEFAULT_ALERTS);
  const [modal, setModal] = React.useState(null); // null | { kind: 'stock', holding, account } | { kind: 'alerts' }
  const [liveStatus, setLiveStatus] = React.useState(window.OUROBOROS_LIVE_STATUS || null);
  const [liveAccounts, setLiveAccounts] = React.useState(window.OUROBOROS_LIVE_ACCOUNTS || null);

  React.useEffect(() => {
    if (!window.OUROBOROS_LIVE) return undefined;
    return window.OUROBOROS_LIVE.subscribe((status, accounts) => {
      setLiveStatus(status || null);
      setLiveAccounts(Array.isArray(accounts) ? accounts : null);
    });
  }, []);

  const accounts = liveAccounts && liveAccounts.length ? liveAccounts : ACCOUNTS;
  const fixedScene = sceneFromQuery();
  const activeScene = fixedScene || t.scene;
  const nativeEmbed = queryFlag('native') && (activeScene === 'overview' || activeScene === 'reflection' || activeScene === 'history');
  const focused = focusAccount === 'all'
    ? aggregateAccounts(accounts)
    : (accounts.find(a => a.id === focusAccount) || accounts[0] || aggregateAccounts(accounts));
  const generatedAt = liveStatus && (liveStatus.generated_at_jst || liveStatus.generated_at || liveStatus.updated_at_jst || liveStatus.state_updated_at);
  const liveBadge = liveStatus ? `${liveStatus.status_level || 'LIVE'}${generatedAt ? ' · ' + generatedAt : ''}` : 'ZIP DESIGN PREVIEW';
  const modeText = liveStatus
    ? `${SCENE_LABELS[activeScene]} / ${liveStatus.effective_stage || '-'} / ${liveStatus.trade_enabled ? '取引ON' : '取引OFF'} / ${liveStatus.runner_alive ? 'bot稼働' : 'bot停止'}`
    : `証券口座 × ${accounts.length} · ${classificationTitle(t.classification)}構成 · リサイズ・並び替え対応 · ドリルダウン対応`;

  const stageBg = t.dark ? '#0a0c12' : '#e7ecf3';
  const textColor = t.dark ? '#e7ecf3' : '#0a0c12';

  const openStock = (h, a) => setModal({ kind: 'stock', holding: h, account: a });
  const openAlerts = () => setModal({ kind: 'alerts' });
  const closeModal = () => setModal(null);

  if (nativeEmbed) {
    return (
      <div style={{
        minHeight: '100vh',
        background: 'radial-gradient(130% 90% at 8% 0%, #65728f 0%, #374159 40%, #171d2e 70%, #080a10 100%)',
        color: '#fff',
        fontFamily: '-apple-system, "SF Pro Display", system-ui, sans-serif',
        overflowX: 'hidden',
      }}>
        <AnimationStyles />
        {activeScene === 'overview' && (
          <OuroborosOverviewScene
            status={liveStatus}
            accounts={accounts}
            dark={t.dark}
            accent={t.accent}
            sectorViz={t.sectorViz}
            plFormat={t.plFormat}
            embedded
          />
        )}
        {activeScene === 'reflection' && (
          <OuroborosReflectionScene
            status={liveStatus}
            accounts={accounts}
            dark={t.dark}
            accent={t.accent}
            plFormat={t.plFormat}
            embedded
          />
        )}
        {activeScene === 'history' && (
          <OuroborosTradesScene
            status={liveStatus}
            embedded
          />
        )}
      </div>
    );
  }

  return (
    <div style={{
      minHeight: '100vh', background: stageBg, color: textColor,
      fontFamily: '-apple-system, "SF Pro Text", system-ui, sans-serif',
      padding: '36px 36px 80px', boxSizing: 'border-box',
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 24,
    }}>
      <AnimationStyles />

      {/* Header */}
      <div style={{ width: '100%', maxWidth: 1280, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1.2, textTransform: 'uppercase', opacity: 0.5 }}>{liveStatus ? 'Ouroboros Live · iOS' : 'Portfolio Widget · iOS'}</div>
          <h1 style={{ margin: '4px 0 0', fontSize: 28, fontWeight: 700, letterSpacing: -0.6 }}>
            {liveStatus ? 'Ouroboros ウィジェット' : 'ポートフォリオ・ウィジェット'}
          </h1>
          <div style={{ fontSize: 13, marginTop: 4, opacity: 0.6, letterSpacing: -0.1 }}>
            {modeText}
          </div>
          <div style={{ marginTop: 8, display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '6px 10px', borderRadius: 999,
            background: liveStatus ? 'rgba(22,199,132,0.12)' : 'rgba(240,178,60,0.12)',
            color: liveStatus ? '#16C784' : '#F0B23C',
            border: '0.5px solid ' + (liveStatus ? 'rgba(22,199,132,0.28)' : 'rgba(240,178,60,0.28)'),
            fontSize: 11, fontWeight: 700, letterSpacing: 0.2 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'currentColor' }} />
            {liveBadge}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {SWITCHER_SCENES.map(s => (
            <button key={s} onClick={() => fixedScene ? null : setTweak('scene', s)} style={{
              padding: '8px 14px', borderRadius: 999,
              border: activeScene === s ? '1px solid currentColor' : '1px solid transparent',
              background: activeScene === s ? (t.dark ? '#1c2030' : '#fff') : 'transparent',
              color: textColor, cursor: fixedScene ? 'default' : 'pointer',
              opacity: fixedScene && activeScene !== s ? 0.45 : 1,
              fontSize: 12, fontWeight: 600, letterSpacing: -0.1, textTransform: 'capitalize',
            }}>{SCENE_LABELS[s]}</button>
          ))}
        </div>
      </div>

      {/* Stage */}
      <div style={{
        display: 'flex', gap: 32, alignItems: 'flex-start', justifyContent: 'center',
        flexWrap: 'wrap',
      }}>
        {/* Device frame */}
        {(() => {
          const isLandscape = activeScene === 'standby';
          const sceneW = isLandscape ? 874 : 402;
          const sceneH = isLandscape ? 402 : 874;
          return (
        <div style={{
          position: 'relative',
          boxShadow: t.dark
            ? '0 0 0 9px #1a1d24, 0 0 0 11px #2a2f3c, 0 40px 80px rgba(0,0,0,0.45)'
            : '0 0 0 9px #1a1d24, 0 0 0 11px #2a2f3c, 0 40px 80px rgba(15,23,42,0.18)',
          borderRadius: 56,
        }}>
          <div style={{ position: 'relative', width: sceneW, height: sceneH, borderRadius: 48, overflow: 'hidden' }}>
            {activeScene === 'overview' && (
              <OuroborosOverviewScene
                status={liveStatus}
                accounts={accounts}
                dark={t.dark}
                accent={t.accent}
                sectorViz={t.sectorViz}
                plFormat={t.plFormat}
              />
            )}
            {activeScene === 'reflection' && (
              <OuroborosReflectionScene
                status={liveStatus}
                accounts={accounts}
                dark={t.dark}
                accent={t.accent}
                plFormat={t.plFormat}
              />
            )}
            {activeScene === 'history' && (
              <OuroborosTradesScene
                status={liveStatus}
              />
            )}
            {activeScene === 'home' && (
              <HomeScreen
                widgets={widgets} setWidgets={setWidgets}
                dark={t.dark} accent={t.accent}
                sectorViz={t.sectorViz} plFormat={t.plFormat} classification={t.classification}
                editing={editing} setEditing={setEditing}
                accounts={accounts}
                onTapHolding={openStock}
                onOpenAlerts={openAlerts}
              />
            )}
            {activeScene === 'lock' && <LockScreen accounts={accounts} dark={t.dark} accent={t.accent} />}
            {activeScene === 'standby' && <StandByScene accounts={accounts} dark={t.dark} accent={t.accent} sectorViz={t.sectorViz} plFormat={t.plFormat} />}

            {/* Modals — relative to the iPhone screen */}
            {modal && modal.kind === 'stock' && (
              <StockDetail holding={modal.holding} account={modal.account}
                dark={t.dark} accent={t.accent} plFormat={t.plFormat}
                onClose={closeModal} />
            )}
            {modal && modal.kind === 'alerts' && (
              <AlertsSettings alerts={alerts} setAlerts={setAlerts}
                dark={t.dark} accent={t.accent}
                onClose={closeModal} />
            )}
          </div>
        </div>
          );
        })()}

        {/* Right rail */}
        {t.showGallery && activeScene === 'home' && (
          <SizeGallery account={focused} accounts={accounts}
                       focusAccount={focusAccount} setFocusAccount={setFocusAccount}
                       dark={t.dark} accent={t.accent}
                       sectorViz={t.sectorViz} plFormat={t.plFormat} classification={t.classification}
                       onTapHolding={openStock}
                       onOpenAlerts={openAlerts} />
        )}
        {t.showGallery && activeScene === 'lock' && (
          <LockWidgetGallery accounts={accounts}
                             dark={t.dark} accent={t.accent}
                             sectorViz={t.sectorViz} plFormat={t.plFormat} classification={t.classification} />
        )}
      </div>

      {/* Help row */}
      <div style={{
        maxWidth: 1280, width: '100%', marginTop: 8,
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 12,
        fontSize: 12, opacity: 0.75, letterSpacing: -0.1,
      }}>
        <Hint icon="✋" title="編集モード" body="ホーム画面をダブルタップ → ウィジェットがウィグル。ドラッグで並び替え、(−) で削除、右下バッジでサイズ循環。" />
        <Hint icon="↺" title="口座切替" body="通常時にウィジェットをタップで表示口座を切替 (All → Robinhood → Schwab → …)。" />
        <Hint icon="📊" title="銘柄ドリルダウン" body="XLウィジェット内の銘柄行をタップで個別銘柄詳細シート (チャート・統計・ニュース・ポジション)。" />
        <Hint icon="🔔" title="アラート設定" body="iPhone右上のベルアイコン (またはTweaks→Open alerts) で通知設定シート。" />
      </div>

      {/* Tweaks panel */}
      <TweaksPanel title="Tweaks">
        <TweakSection label="Theme" />
        <TweakToggle label="Dark mode" value={t.dark} onChange={(v) => setTweak('dark', v)} />
        <TweakColor  label="Accent" value={t.accent} options={ACCENT_OPTIONS} onChange={(v) => setTweak('accent', v)} />

        <TweakSection label="Allocation" />
        <TweakRadio  label="Group by" value={t.classification} options={CLASSIFICATION_OPTIONS}
          onChange={(v) => setTweak('classification', v)} />
        <TweakSelect label="Chart type" value={t.sectorViz} options={SECTOR_VIZ_OPTIONS}
          onChange={(v) => setTweak('sectorViz', v)} />
        <TweakRadio  label="P/L format" value={t.plFormat} options={PL_FORMAT_OPTIONS}
          onChange={(v) => setTweak('plFormat', v)} />

        <TweakSection label="Scene" />
        <TweakSelect label="View" value={t.scene} options={SCENE_OPTIONS}
          onChange={(v) => setTweak('scene', v)} />
        <TweakToggle label="Size gallery" value={t.showGallery} onChange={(v) => setTweak('showGallery', v)} />
        <TweakButton label={editing ? 'Exit edit mode' : 'Enter edit mode'}
          onClick={() => setEditing(e => !e)} />

        <TweakSection label="Demos" />
        <TweakButton label="Open alerts settings" onClick={openAlerts} />
        <TweakButton label="Open NVDA detail" onClick={() => openStock(
          accounts[0].holdings.find(h => h.ticker === 'NVDA') || accounts[0].holdings[0],
          accounts[0]
        )} />
        <TweakButton label="Open BTC detail" onClick={() => openStock(
          accounts[2].holdings.find(h => h.ticker === 'BTC') || accounts[2].holdings[0],
          accounts[2]
        )} />

        <TweakSection label="Layout presets" />
        <TweakButton label="Reset layout" onClick={() => setWidgets(DEFAULT_LAYOUT)} />
        <TweakButton label="Compact (4 smalls)" onClick={() => setWidgets([
          { id: 'a', size: 'small', accountId: 'robinhood' },
          { id: 'b', size: 'small', accountId: 'schwab' },
          { id: 'c', size: 'small', accountId: 'coinbase' },
          { id: 'd', size: 'small', accountId: 'binance' },
          { id: 'e', size: 'medium', accountId: 'all' },
        ])} />
        <TweakButton label="Deep dive (XL all)" onClick={() => setWidgets([
          { id: 'a', size: 'xl', accountId: 'all' },
          { id: 'b', size: 'medium', accountId: 'robinhood' },
        ])} />
      </TweaksPanel>
    </div>
  );
}

function Hint({ icon, title, body }) {
  return (
    <div style={{ display: 'flex', gap: 10, padding: '10px 12px', borderRadius: 12,
      background: 'rgba(127,127,127,0.08)', border: '0.5px solid rgba(127,127,127,0.15)' }}>
      <span style={{ fontSize: 16, lineHeight: 1 }}>{icon}</span>
      <div>
        <div style={{ fontWeight: 700, letterSpacing: -0.1 }}>{title}</div>
        <div style={{ marginTop: 2, opacity: 0.85 }}>{body}</div>
      </div>
    </div>
  );
}

// ─── Right-rail size gallery ───────────────────────────────────────────
function SizeGallery({ account, accounts, focusAccount, setFocusAccount, dark, accent, sectorViz, plFormat, classification, onTapHolding, onOpenAlerts }) {
  const labelSt = {
    color: dark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)',
    fontSize: 10, fontWeight: 600, letterSpacing: 0.8, textTransform: 'uppercase',
  };
  const allAcct = focusAccount === 'all' ? aggregateAccounts(accounts) : account;

  return (
    <div style={{
      width: 380, display: 'flex', flexDirection: 'column', gap: 18,
      padding: '12px 16px 16px', borderRadius: 28,
      background: dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.025)',
      border: '0.5px solid ' + (dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'),
    }}>
      <div>
        <div style={labelSt}>Account focus</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          <FocusChip id="all" name="All" color="#ffffff" current={focusAccount} onClick={() => setFocusAccount('all')} dark={dark} />
          {accounts.map(a => (
            <FocusChip key={a.id} id={a.id} name={a.short + ' ' + a.name} color={a.brandColor}
              current={focusAccount} onClick={() => setFocusAccount(a.id)} dark={dark} />
          ))}
        </div>
      </div>

      <div>
        <div style={labelSt}>Sizes · {classificationTitle(classification)} view</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 12, alignItems: 'center' }}>
          <GalleryItem name="Small · 2×2" dark={dark}>
            <WidgetSmall account={allAcct} dark={dark} accent={accent} sectorViz={sectorViz} plFormat={plFormat} classification={classification} />
          </GalleryItem>
          <GalleryItem name="Medium · 4×2" dark={dark}>
            <WidgetMedium account={allAcct} dark={dark} accent={accent} sectorViz={sectorViz} plFormat={plFormat} classification={classification} />
          </GalleryItem>
          <GalleryItem name="Large · 4×4" dark={dark}>
            <WidgetLarge account={allAcct} dark={dark} accent={accent} sectorViz={sectorViz} plFormat={plFormat} classification={classification} />
          </GalleryItem>
        </div>
      </div>

      <div>
        <div style={labelSt}>Lock screen complications</div>
        <div style={{
          display: 'flex', gap: 12, alignItems: 'center',
          padding: 16, borderRadius: 18, marginTop: 12,
          background: 'linear-gradient(135deg, #1d2543 0%, #06070d 100%)',
        }}>
          <WidgetCircular account={allAcct} />
          <WidgetInline account={allAcct} plFormat={plFormat} />
        </div>
      </div>

      <div>
        <div style={labelSt}>Quick actions</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <RailBtn dark={dark} onClick={onOpenAlerts}>🔔 Alerts</RailBtn>
          {allAcct.holdings && allAcct.holdings[0] && (() => {
            const top = allAcct.holdings[0];
            // Find the account that actually owns this holding (top.account is the short code when from aggregate)
            const owner = accounts.find(a => a.holdings.some(h => h.ticker === top.ticker)) || account || accounts[0];
            return (
              <RailBtn dark={dark} onClick={() => onTapHolding(top, owner)}>
                📊 {top.ticker} detail
              </RailBtn>
            );
          })()}
        </div>
      </div>
    </div>
  );
}

function RailBtn({ children, dark, onClick }) {
  return (
    <button onClick={onClick} style={{
      padding: '6px 12px', borderRadius: 999,
      background: dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)',
      border: '0.5px solid ' + (dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.1)'),
      color: dark ? '#fff' : '#000', cursor: 'pointer',
      fontSize: 12, fontWeight: 600, letterSpacing: -0.1,
      fontFamily: 'inherit',
    }}>{children}</button>
  );
}

function FocusChip({ id, name, color, current, onClick, dark }) {
  const active = current === id;
  return (
    <button onClick={onClick} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px', borderRadius: 999,
      background: active ? (dark ? '#fff' : '#0a0c12') : 'transparent',
      color: active ? (dark ? '#0a0c12' : '#fff') : (dark ? '#fff' : '#0a0c12'),
      border: '0.5px solid ' + (active ? 'transparent' : (dark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.15)')),
      fontSize: 11, fontWeight: 600, cursor: 'pointer', letterSpacing: -0.1,
      fontFamily: 'inherit',
    }}>
      <span style={{ width: 7, height: 7, borderRadius: 2, background: color, flexShrink: 0 }} />
      {name}
    </button>
  );
}

function GalleryItem({ name, dark, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center' }}>
      <div style={{
        fontSize: 10, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase',
        color: dark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)',
      }}>{name}</div>
      {children}
    </div>
  );
}

function homeTone(tone) {
  if (tone === 'ok') return { bg: 'rgba(22,199,132,0.16)', border: 'rgba(22,199,132,0.36)', color: '#5DFFA6' };
  if (tone === 'warn') return { bg: 'rgba(240,178,60,0.18)', border: 'rgba(240,178,60,0.40)', color: '#F0B23C' };
  if (tone === 'alert') return { bg: 'rgba(234,57,67,0.18)', border: 'rgba(234,57,67,0.42)', color: '#FF8E94' };
  return { bg: 'rgba(255,255,255,0.10)', border: 'rgba(255,255,255,0.18)', color: '#E7ECF3' };
}

function compactJpy(value) {
  return fmtMoney(Number(value) || 0, 'JPY', true);
}

function compactPct(value, digits = 1) {
  const n = Number(value) || 0;
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

function HomeStyleSceneShell({ title, kicker, statusText, statusTone = 'neutral', children, footer, embedded = false }) {
  const tone = homeTone(statusTone);
  const now = new Date();
  const time = now.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  return (
    <div style={{
      width: embedded ? '100%' : 402,
      minHeight: embedded ? '100vh' : undefined,
      height: embedded ? 'auto' : 874,
      position: 'relative',
      overflow: embedded ? 'visible' : 'hidden',
      background: 'radial-gradient(130% 90% at 8% 0%, #65728f 0%, #374159 40%, #171d2e 70%, #080a10 100%)',
      color: '#fff', fontFamily: '-apple-system, "SF Pro Display", system-ui, sans-serif',
      padding: embedded ? '24px 18px 118px' : '56px 22px 26px',
      boxSizing: 'border-box',
    }}>
      {!embedded && (
        <div style={{
          position: 'absolute', top: 11, left: '50%', transform: 'translateX(-50%)',
          width: 126, height: 37, borderRadius: 24, background: '#000', opacity: 0.96,
        }} />
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        {!embedded && <div style={{ fontSize: 30, fontWeight: 850, letterSpacing: -1.2 }}>{time}</div>}
        {embedded && <div style={{ fontSize: 12, fontWeight: 850, letterSpacing: 1.4, opacity: 0.58, textTransform: 'uppercase' }}>{kicker}</div>}
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '8px 12px', borderRadius: 999, background: tone.bg,
          border: '1px solid ' + tone.border, color: tone.color,
          fontSize: 12, fontWeight: 850, letterSpacing: 0.5, textTransform: 'uppercase',
        }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'currentColor' }} />
          {statusText}
        </div>
      </div>
      <div style={{ marginBottom: 18 }}>
        {!embedded && <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 1.6, opacity: 0.58, textTransform: 'uppercase' }}>{kicker}</div>}
        <div style={{ marginTop: embedded ? 0 : 7, fontSize: embedded ? 38 : 42, lineHeight: 1.02, fontWeight: 900, letterSpacing: -1.8 }}>{title}</div>
      </div>
      {children}
      {footer && !embedded && (
        <div style={{ position: 'absolute', left: 22, right: 22, bottom: 22 }}>
          {footer}
        </div>
      )}
    </div>
  );
}

function HomeMetricCard({ label, value, detail, tone = 'neutral' }) {
  const t = homeTone(tone);
  return (
    <div style={{
      minHeight: 118, borderRadius: 25, padding: 18, boxSizing: 'border-box',
      minWidth: 0, overflow: 'hidden',
      background: 'linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.06))',
      border: '1px solid rgba(255,255,255,0.16)',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.12)',
    }}>
      <div style={{ fontSize: 12, fontWeight: 850, letterSpacing: 1.1, opacity: 0.58, textTransform: 'uppercase' }}>{label}</div>
      <div style={{
        marginTop: 12, fontSize: 30, fontWeight: 900, letterSpacing: -1, color: t.color,
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        fontVariantNumeric: 'tabular-nums',
      }}>{value}</div>
      <div style={{ marginTop: 6, fontSize: 14, lineHeight: 1.25, opacity: 0.72 }}>{detail}</div>
    </div>
  );
}

function OverviewCircleTile({ account, label, detail, tone = 'neutral' }) {
  const t = homeTone(tone);
  const up = (account && account.todayPL) >= 0;
  return (
    <div style={{
      minWidth: 0,
      borderRadius: 26,
      padding: '13px 9px 12px',
      background: 'linear-gradient(160deg, rgba(255,255,255,0.18), rgba(255,255,255,0.06))',
      border: '1px solid rgba(255,255,255,0.14)',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.12)',
      textAlign: 'center',
    }}>
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 8 }}>
        <div style={{
          width: 68, height: 68, borderRadius: '50%',
          background: t.bg,
          border: '1px solid ' + t.border,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          position: 'relative', overflow: 'hidden',
          boxShadow: '0 12px 26px rgba(0,0,0,0.20), inset 0 1px 0 rgba(255,255,255,0.14)',
        }}>
          <div style={{ position: 'absolute', inset: 5 }}>
            <AnimatedDonut data={(account && account.sectors) || [{ name: 'Cash', value: 1 }]} size={58} thickness={5} dark accent={t.color} />
          </div>
          <div style={{
            width: 43, height: 43, borderRadius: '50%',
            background: 'rgba(9,12,20,0.70)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            position: 'relative',
          }}>
            <div style={{ fontSize: 10, fontWeight: 900, lineHeight: 1, color: t.color }}>{account && account.short}</div>
            <div style={{ marginTop: 2, fontSize: 9, fontWeight: 850, color: up ? '#5DFFA6' : '#FF8E94' }}>
              {(up ? '+' : '') + Number((account && account.todayPLPct) || 0).toFixed(1)}%
            </div>
          </div>
        </div>
      </div>
      <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: 0.3 }}>{label}</div>
      <div style={{ marginTop: 4, fontSize: 10.5, lineHeight: 1.18, opacity: 0.65, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{detail}</div>
    </div>
  );
}

function OverviewDonutHero({ account, status, goal, weekly, drift }) {
  const alert = status && status.status_level === 'ALERT';
  const warn = status && status.status_level === 'WARN';
  const tone = homeTone(alert ? 'alert' : warn ? 'warn' : 'ok');
  const runnerOn = Boolean(status && status.runner_alive);
  const tradeOn = Boolean(status && status.trade_enabled);
  const goalText = `${compactJpy(goal.pnl_jpy)}/${compactJpy(goal.goal_jpy || 100)}`;
  const weekText = compactJpy(weekly.pnl_jpy_sum);
  const valueMissing = Boolean(account && account.valueMissing);
  const valueText = valueMissing ? '---' : fmtMoney(account && account.value, 'JPY', true);
  const detailText = valueMissing
    ? ((account && account.missingReason) || '口座API設定待ち')
    : `${runnerOn ? 'bot稼働中' : 'bot停止'} ・ あと${drift.remaining_samples ?? 0}件`;
  return (
    <div style={{
      borderRadius: 36,
      padding: 18,
      marginBottom: 16,
      background: 'linear-gradient(145deg, rgba(255,255,255,0.21), rgba(255,255,255,0.07))',
      border: '1px solid rgba(255,255,255,0.18)',
      boxShadow: '0 18px 42px rgba(0,0,0,0.20), inset 0 1px 0 rgba(255,255,255,0.13)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
        <div style={{
          width: 132, height: 132, borderRadius: '50%',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          position: 'relative', flexShrink: 0,
          background: tone.bg,
          border: '1px solid ' + tone.border,
          boxShadow: '0 20px 50px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.16)',
        }}>
          <AnimatedDonut data={(account && account.sectors) || [{ name: 'Cash', value: 1 }]} size={118} thickness={12} dark accent={tone.color} />
          <div style={{
            position: 'absolute', inset: 26, borderRadius: '50%',
            background: 'rgba(8,10,16,0.76)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 11, fontWeight: 900, color: tone.color, letterSpacing: 0.6 }}>{runnerOn ? 'RUN' : 'STOP'}</div>
            <div style={{ marginTop: 4, fontSize: 19, fontWeight: 950, letterSpacing: -0.7 }}>{tradeOn ? 'ON' : 'OFF'}</div>
            <div style={{ marginTop: 2, fontSize: 9.5, opacity: 0.62 }}>{status && status.status_level || 'LIVE'}</div>
          </div>
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: 1.2, opacity: 0.56, textTransform: 'uppercase' }}>Balance</div>
          <div style={{ marginTop: 6, fontSize: valueMissing ? 28 : 35, lineHeight: 1, fontWeight: 950, letterSpacing: -1.7 }}>{valueText}</div>
          <div style={{ marginTop: 10, fontSize: 13.5, lineHeight: 1.35, opacity: 0.74, fontWeight: 750 }}>
            {detailText}
          </div>
          <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9 }}>
            <div style={{ borderRadius: 18, padding: '9px 10px', background: 'rgba(255,255,255,0.09)', border: '1px solid rgba(255,255,255,0.10)' }}>
              <div style={{ fontSize: 9.5, fontWeight: 850, opacity: 0.56, textTransform: 'uppercase' }}>Goal</div>
              <div style={{
                marginTop: 3, fontSize: 14, fontWeight: 900,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                fontVariantNumeric: 'tabular-nums',
              }}>{goalText}</div>
            </div>
            <div style={{ borderRadius: 18, padding: '9px 10px', background: 'rgba(255,255,255,0.09)', border: '1px solid rgba(255,255,255,0.10)' }}>
              <div style={{ fontSize: 9.5, fontWeight: 850, opacity: 0.56, textTransform: 'uppercase' }}>Week</div>
              <div style={{
                marginTop: 3, fontSize: 14, fontWeight: 900,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                fontVariantNumeric: 'tabular-nums',
              }}>{weekText}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function AccountStackCard({ accounts, weekly }) {
  const rows = accounts.slice(0, 4);
  const weekPnl = Number(weekly.pnl_jpy_sum) || 0;
  return (
    <div style={{
      borderRadius: 30,
      padding: 16,
      marginBottom: 14,
      background: 'linear-gradient(145deg, rgba(255,255,255,0.14), rgba(255,255,255,0.052))',
      border: '1px solid rgba(255,255,255,0.13)',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.10)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: 1.2, opacity: 0.56, textTransform: 'uppercase' }}>Account Stack</div>
          <div style={{ marginTop: 3, fontSize: 13, opacity: 0.7 }}>口座・目標・週次・運用を一括監視</div>
        </div>
        <div style={{
          padding: '6px 9px', borderRadius: 999,
          background: weekPnl >= 0 ? 'rgba(22,199,132,0.14)' : 'rgba(240,178,60,0.16)',
          color: weekPnl >= 0 ? '#5DFFA6' : '#F0B23C',
          fontSize: 11, fontWeight: 900, whiteSpace: 'nowrap',
        }}>{fmtMoney(weekPnl, 'JPY', false)}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {rows.map((a) => {
          const up = (Number(a.todayPL) || 0) >= 0;
          const sectors = Array.isArray(a.sectors) ? a.sectors.slice(0, 3) : [];
          const valueMissing = Boolean(a.valueMissing);
          return (
            <div key={a.id} style={{
              minWidth: 0,
              borderRadius: 21,
              padding: '11px 12px',
              background: 'rgba(255,255,255,0.075)',
              border: '1px solid rgba(255,255,255,0.09)',
            }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 3, background: a.brandColor, flexShrink: 0 }} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 950, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.short} {a.name}</div>
                    <div style={{ marginTop: 2, fontSize: 10.5, opacity: 0.56, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.type || 'account'}</div>
                  </div>
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ fontSize: valueMissing ? 11 : 19, fontWeight: 950, letterSpacing: valueMissing ? 0 : -0.7, fontVariantNumeric: 'tabular-nums', color: valueMissing ? 'rgba(255,255,255,0.45)' : 'inherit' }}>{valueMissing ? (a.missingReason || '---') : fmtMoney(a.value, 'JPY', false)}</div>
                  <div style={{ marginTop: 2, fontSize: 11.5, fontWeight: 850, color: up ? '#5DFFA6' : '#FF8E94' }}>
                    {fmtMoney(a.todayPL, 'JPY', false)} / {compactPct(a.todayPLPct)}
                  </div>
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 7, marginTop: 10 }}>
                <div style={{ borderRadius: 13, padding: '7px 8px', background: 'rgba(255,255,255,0.065)', minWidth: 0 }}>
                  <div style={{ fontSize: 9, opacity: 0.52, fontWeight: 850, textTransform: 'uppercase' }}>Cash</div>
                  <div style={{ marginTop: 3, fontSize: 11.5, fontWeight: 900, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{valueMissing ? '-' : fmtMoney(a.cash || 0, 'JPY', false)}</div>
                </div>
                <div style={{ borderRadius: 13, padding: '7px 8px', background: 'rgba(255,255,255,0.065)', minWidth: 0 }}>
                  <div style={{ fontSize: 9, opacity: 0.52, fontWeight: 850, textTransform: 'uppercase' }}>Week%</div>
                  <div style={{ marginTop: 3, fontSize: 11.5, fontWeight: 900, color: (Number(a.weekPLPct) || 0) >= 0 ? '#5DFFA6' : '#FF8E94' }}>{compactPct(a.weekPLPct)}</div>
                </div>
                <div style={{ borderRadius: 13, padding: '7px 8px', background: 'rgba(255,255,255,0.065)', minWidth: 0 }}>
                  <div style={{ fontSize: 9, opacity: 0.52, fontWeight: 850, textTransform: 'uppercase' }}>Top</div>
                  <div style={{ marginTop: 3, fontSize: 11.5, fontWeight: 900, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {sectors.map(s => s.name).join(' / ') || '-'}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ShadowDeskCard({ status, weekly, drift, latest }) {
  const reflection = status && status.latest_reflection ? status.latest_reflection : {};
  const actions = Array.isArray(reflection.next_actions) ? reflection.next_actions : [];
  const sample = reflection.sample_confidence || (drift.remaining_samples ? `あと${drift.remaining_samples}件` : 'monitoring');
  const shadowTone = drift.resume_ready ? 'ok' : drift.status === 'INSUFFICIENT' ? 'warn' : 'neutral';
  const tone = homeTone(shadowTone);
  const latestText = latest.result || 'NO SIGNAL';
  return (
    <div style={{
      borderRadius: 30,
      padding: 16,
      marginBottom: 14,
      background: 'linear-gradient(145deg, rgba(255,255,255,0.14), rgba(255,255,255,0.052))',
      border: '1px solid rgba(255,255,255,0.13)',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.10)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: 1.2, opacity: 0.56, textTransform: 'uppercase' }}>Shadow Desk</div>
          <div style={{ marginTop: 5, fontSize: 21, lineHeight: 1.05, fontWeight: 950, color: tone.color }}>
            {drift.status || 'MONITOR'}
          </div>
        </div>
        <div style={{
          width: 76, height: 76, borderRadius: '50%',
          position: 'relative', flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: tone.bg,
          border: '1px solid ' + tone.border,
        }}>
          <AnimatedDonut
            data={[
              { name: 'Health', value: Math.max(1, Number(weekly.win_rate_pct) || 1) },
              { name: 'Energy', value: Math.max(1, Number(drift.remaining_samples) || 1) },
              { name: 'Cash', value: Math.max(1, actions.length || 1) },
            ]}
            size={66}
            thickness={7}
            dark
            accent={tone.color}
          />
          <div style={{ position: 'absolute', fontSize: 10, fontWeight: 950, color: tone.color }}>SH</div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 13 }}>
        <div style={{ borderRadius: 16, padding: '9px 8px', background: 'rgba(255,255,255,0.075)', minWidth: 0 }}>
          <div style={{ fontSize: 9.5, fontWeight: 850, opacity: 0.55, textTransform: 'uppercase' }}>Latest</div>
          <div style={{ marginTop: 4, fontSize: 11.5, fontWeight: 900, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{latestText}</div>
        </div>
        <div style={{ borderRadius: 16, padding: '9px 8px', background: 'rgba(255,255,255,0.075)', minWidth: 0 }}>
          <div style={{ fontSize: 9.5, fontWeight: 850, opacity: 0.55, textTransform: 'uppercase' }}>Sample</div>
          <div style={{ marginTop: 4, fontSize: 11.5, fontWeight: 900, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sample}</div>
        </div>
        <div style={{ borderRadius: 16, padding: '9px 8px', background: 'rgba(255,255,255,0.075)', minWidth: 0 }}>
          <div style={{ fontSize: 9.5, fontWeight: 850, opacity: 0.55, textTransform: 'uppercase' }}>Action</div>
          <div style={{ marginTop: 4, fontSize: 11.5, fontWeight: 900 }}>{actions.length || 0}件</div>
        </div>
      </div>
    </div>
  );
}

function OuroborosOverviewScene({ status, accounts, dark, accent, sectorViz, plFormat, embedded = false }) {
  const allAcct = aggregateAccounts(accounts);
  const primaryAcct = accounts[0] || allAcct;
  const goal = status && status.goal ? status.goal : {};
  const weekly = status && status.weekly ? status.weekly : {};
  const drift = status && status.drift ? status.drift : {};
  const latest = status && status.latest_trade ? status.latest_trade : {};
  const alert = status && status.status_level === 'ALERT';
  const warn = status && status.status_level === 'WARN';
  const tradeOn = Boolean(status && status.trade_enabled);
  const runnerOn = Boolean(status && status.runner_alive);
  const winRate = Number(weekly.win_rate_pct || 0);
  const title = `${status && status.effective_stage ? status.effective_stage : 'Overview'} / ${tradeOn ? '取引ON' : '取引OFF'}`;
  return (
    <HomeStyleSceneShell
      kicker="Ouroboros Overview"
      title={title}
      statusText={alert ? 'ALERT' : warn ? 'WATCH' : 'LIVE'}
      statusTone={alert ? 'alert' : warn ? 'warn' : 'ok'}
      footer={<div style={{ height: 5, borderRadius: 999, background: 'rgba(255,255,255,0.72)', width: 132, margin: '0 auto' }} />}
      embedded={embedded}
    >
      <OverviewDonutHero account={primaryAcct} status={status || {}} goal={goal} weekly={weekly} drift={drift} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10, marginBottom: 16 }}>
        <OverviewCircleTile account={accounts[0] || allAcct} label="Live" detail={runnerOn ? '稼働中' : '停止'} tone={runnerOn ? 'ok' : 'alert'} />
        <OverviewCircleTile account={accounts[1] || allAcct} label="Goal" detail={`残り ${goal.remaining_jpy ?? '-'}円`} tone={goal.achieved ? 'ok' : 'neutral'} />
        <OverviewCircleTile account={accounts[2] || allAcct} label="Week" detail={`WR ${winRate.toFixed(1)}%`} tone={(weekly.pnl_jpy_sum || 0) >= 0 ? 'ok' : 'warn'} />
        <OverviewCircleTile account={accounts[3] || allAcct} label="Drift" detail={drift.status || '確認中'} tone={warn ? 'warn' : 'ok'} />
      </div>
      <AccountStackCard accounts={accounts.length ? accounts : [allAcct]} weekly={weekly} />
      {(() => {
        const pc = (status && status.pnl_curve) || {};
        if (!pc.available || !Array.isArray(pc.points) || pc.points.length < 2) return null;
        const total = Number(pc.total_pnl_jpy || 0);
        const wr = Number(pc.win_rate_pct || 0);
        const cn = Number(pc.closed_n || 0);
        const best = Number(pc.best_pnl_jpy || 0);
        const worst = Number(pc.worst_pnl_jpy || 0);
        const color = total >= 0 ? '#34d399' : '#fb7185';
        return (
          <div style={{ borderRadius: 24, padding: '14px 16px', marginBottom: 14, background: 'linear-gradient(145deg, rgba(255,255,255,0.12), rgba(255,255,255,0.045))', border: '1px solid rgba(255,255,255,0.11)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: 1.1, opacity: 0.56, textTransform: 'uppercase' }}>P/L Curve</div>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <span style={{ fontSize: 11.5, fontWeight: 800, opacity: 0.7 }}>WR {wr.toFixed(0)}% / {cn}件</span>
                <span style={{ fontSize: 14, fontWeight: 950, color, letterSpacing: -0.5 }}>{total >= 0 ? '+' : ''}{total.toFixed(0)}円</span>
              </div>
            </div>
            <div style={{ overflow: 'hidden', borderRadius: 8 }}>
              <AnimatedSparkline data={pc.points} width={350} height={38} color={color} dark duration={900} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 11, opacity: 0.55 }}>
              <span>Best <span style={{ color: '#34d399', fontWeight: 800 }}>+{best.toFixed(0)}円</span></span>
              <span>Worst <span style={{ color: '#fb7185', fontWeight: 800 }}>{worst.toFixed(0)}円</span></span>
            </div>
          </div>
        );
      })()}
      <ShadowDeskCard status={status || {}} weekly={weekly} drift={drift} latest={latest} />
      <div style={{
        borderRadius: 30,
        padding: 16,
        marginBottom: 14,
        background: 'linear-gradient(145deg, rgba(255,255,255,0.15), rgba(255,255,255,0.055))',
        border: '1px solid rgba(255,255,255,0.13)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: 1.1, opacity: 0.56, textTransform: 'uppercase' }}>Latest</div>
            <div style={{
              marginTop: 5, fontSize: 22, fontWeight: 950, letterSpacing: -0.7,
              color: (latest.pnl_jpy || 0) >= 0 ? '#5DFFA6' : '#F0B23C',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>{latest.result || '-'}</div>
            <div style={{ marginTop: 4, fontSize: 12.5, opacity: 0.68, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {latest.time || '-'} / {compactJpy(latest.pnl_jpy)}
            </div>
          </div>
          <div style={{ width: 84, flexShrink: 0 }}>
            <AnimatedDonut data={allAcct.sectors || [{ name: 'Cash', value: 1 }]} size={84} thickness={10} dark accent={accent || '#5DFFA6'} />
          </div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <HomeMetricCard label="Daily Goal" value={`${compactJpy(goal.pnl_jpy)} / ${compactJpy(goal.goal_jpy || 100)}`} detail={`残り ${compactJpy(goal.remaining_jpy)}`} tone={goal.achieved ? 'ok' : 'neutral'} />
        <HomeMetricCard label="Runner" value={runnerOn ? '稼働' : '停止'} detail={tradeOn ? '取引許可ON' : '取引許可OFF'} tone={runnerOn ? 'ok' : 'alert'} />
      </div>
    </HomeStyleSceneShell>
  );
}

function OuroborosReflectionScene({ status, accounts, dark, accent, plFormat, embedded = false }) {
  const reflection = status && status.latest_reflection ? status.latest_reflection : {};
  const available = Boolean(reflection.available);
  const actions = Array.isArray(reflection.next_actions) ? reflection.next_actions : [];
  const wins = Array.isArray(reflection.win_notes) ? reflection.win_notes : [];
  const losses = Array.isArray(reflection.loss_notes) ? reflection.loss_notes : [];
  const firstAction = actions[0] || wins[0] || losses[0] || '終業反省はまだ生成されていません';
  const adjust = [reflection.shadow_filter_hint, reflection.shadow_htf_hint, reflection.shadow_exit_hint]
    .filter(x => String(x || '').trim())
    .join(' / ');
  return (
    <HomeStyleSceneShell
      kicker="Reflection"
      title={available ? `反省 / ${reflection.goal_achieved ? '達成' : '未達'}` : '反省 / 待機'}
      statusText={available ? (reflection.goal_achieved ? 'DONE' : 'REVIEW') : 'WAIT'}
      statusTone={available ? (reflection.goal_achieved ? 'ok' : 'warn') : 'neutral'}
      footer={<div style={{ height: 5, borderRadius: 999, background: 'rgba(255,255,255,0.72)', width: 132, margin: '0 auto' }} />}
      embedded={embedded}
    >
      <div style={{
        borderRadius: 34, padding: 20, marginBottom: 18,
        background: 'linear-gradient(135deg, rgba(255,255,255,0.20), rgba(255,255,255,0.08))',
        border: '1px solid rgba(255,255,255,0.18)',
      }}>
        <div style={{ fontSize: 13, fontWeight: 850, letterSpacing: 1.1, opacity: 0.62, textTransform: 'uppercase' }}>{reflection.day8 || 'Latest'}</div>
        <div style={{ marginTop: 12, fontSize: 26, lineHeight: 1.15, fontWeight: 900, letterSpacing: -0.7 }}>{firstAction}</div>
        <div style={{ marginTop: 14, fontSize: 14, lineHeight: 1.45, opacity: 0.72 }}>{adjust || `sample ${reflection.sample_confidence || '-'}`}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
        <HomeMetricCard label="Next Action" value={actions.length ? `${actions.length}件` : '-'} detail={actions[1] || actions[0] || '翌日アクション待ち'} tone={actions.length ? 'ok' : 'neutral'} />
        <HomeMetricCard label="Win Note" value={wins.length ? 'あり' : '-'} detail={wins[0] || '勝ちパターンの記録待ち'} tone={wins.length ? 'ok' : 'neutral'} />
        <HomeMetricCard label="Loss Note" value={losses.length ? 'あり' : '-'} detail={losses[0] || '損失メモなし'} tone={losses.length ? 'warn' : 'ok'} />
      </div>
    </HomeStyleSceneShell>
  );
}

function LockWidgetGallery({ accounts, dark, accent, sectorViz, plFormat, classification }) {
  const allAcct = aggregateAccounts(accounts);
  const sample = accounts[0] || allAcct;
  const labelSt = {
    color: dark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)',
    fontSize: 10, fontWeight: 600, letterSpacing: 0.8, textTransform: 'uppercase',
  };
  return (
    <div style={{
      width: 380, display: 'flex', flexDirection: 'column', gap: 18,
      padding: '12px 16px 16px', borderRadius: 28,
      background: dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.025)',
      border: '0.5px solid ' + (dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'),
    }}>
      <div>
        <div style={labelSt}>Lock screen widgets</div>
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}>
          <WidgetInline account={allAcct} dark={dark} plFormat={plFormat} />
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            {accounts.slice(0, 4).map(a => <WidgetCircular key={a.id} account={a} dark={dark} />)}
          </div>
        </div>
      </div>
      <div>
        <div style={labelSt}>Home screen widgets</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 12, alignItems: 'center' }}>
          <GalleryItem name="Small home widget" dark={dark}>
            <WidgetSmall account={sample} dark={dark} accent={accent} sectorViz={sectorViz} plFormat={plFormat} classification={classification} />
          </GalleryItem>
          <GalleryItem name="Medium home widget" dark={dark}>
            <WidgetMedium account={allAcct} dark={dark} accent={accent} sectorViz={sectorViz} plFormat={plFormat} classification={classification} />
          </GalleryItem>
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);

// ─── Trades History Scene ──────────────────────────────────────────────
function OuroborosTradesScene({ status, embedded = false }) {
  const [activeTab, setActiveTab] = React.useState('fx');

  const fxTrades   = Array.isArray(status && status.recent_trades)  ? status.recent_trades  : [];
  const ibkrTrades = Array.isArray(status && status.ibkr_trades)    ? status.ibkr_trades    : [];
  const shTrades   = Array.isArray(status && status.shadow_trades)  ? status.shadow_trades  : [];

  const tabs = [
    { id: 'fx',     label: 'BTC FX',  trades: fxTrades,   currency: 'jpy' },
    { id: 'ibkr',   label: 'IBKR',    trades: ibkrTrades, currency: 'usd' },
    { id: 'shadow', label: 'Shadow',  trades: shTrades,   currency: 'jpy' },
  ];
  const tab = tabs.find(t => t.id === activeTab) || tabs[0];
  const trades = tab.trades;
  const currency = tab.currency;

  function exitColor(reason) {
    if (reason === 'TP') return '#34d399';
    if (reason === 'SL' || reason === 'EARLY_ADVERSE') return '#fb7185';
    if (reason === 'TIMEOUT' || reason === 'EOD') return '#94a3b8';
    return '#fbbf24';
  }
  function exitLabel(reason) {
    if (!reason) return '-';
    const map = { TP:'TP', SL:'SL', EARLY_ADVERSE:'EA', TIMEOUT:'TO', EOD:'EOD', WEAK_PROGRESS:'WP', NEAR_TP_GIVEBACK:'NTG', PROGRESS_REVERSAL:'PR', NO_FOLLOW_THROUGH:'NFT', STALE:'STA' };
    return map[reason] || reason.slice(0, 3);
  }
  function fmtPrice(p, cur) {
    if (p == null) return '-';
    if (cur === 'usd') return '$' + Number(p).toFixed(2);
    return Number(p).toLocaleString('ja-JP');
  }
  function fmtPnl(tr, cur) {
    const v = cur === 'usd' ? tr.pnl_usd : tr.pnl_jpy;
    if (v == null) return '-';
    const n = Number(v);
    if (cur === 'usd') return (n >= 0 ? '+' : '') + n.toFixed(2) + '$';
    return (n >= 0 ? '+' : '') + Math.round(n) + '円';
  }
  function fmtTime(t) {
    if (!t) return '-';
    const m = t.match(/\d{4}-(\d{2})-(\d{2}) (\d{2}):(\d{2})/);
    return m ? m[1] + '/' + m[2] + ' ' + m[3] + ':' + m[4] : t.slice(5, 16);
  }

  const wins   = trades.filter(t => (currency === 'usd' ? t.pnl_usd : t.pnl_jpy) > 0);
  const losses = trades.filter(t => (currency === 'usd' ? t.pnl_usd : t.pnl_jpy) < 0);
  const totalPnl = trades.reduce((s, t) => s + (Number(currency === 'usd' ? t.pnl_usd : t.pnl_jpy) || 0), 0);
  const wr = trades.length > 0 ? Math.round(wins.length / trades.length * 100) : 0;

  function fmtTotal(v, cur) {
    if (cur === 'usd') return (v >= 0 ? '+' : '') + v.toFixed(2) + '$';
    return (v >= 0 ? '+' : '') + Math.round(v) + '円';
  }

  const tabBarStyle = { display: 'flex', gap: 6, marginBottom: 14 };
  const tabBtnStyle = (active) => ({
    flex: 1, padding: '8px 0', borderRadius: 12, border: 'none', cursor: 'pointer',
    fontSize: 12, fontWeight: 900, letterSpacing: 0.4,
    background: active ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.07)',
    color: active ? '#fff' : 'rgba(255,255,255,0.45)',
    transition: 'all 0.15s',
  });

  return (
    React.createElement(HomeStyleSceneShell, {
      kicker: 'Ouroboros Trades',
      title: '取引履歴',
      statusText: trades.length > 0 ? trades.length + '件' : 'WAIT',
      statusTone: totalPnl > 0 ? 'ok' : totalPnl < 0 ? 'alert' : 'neutral',
      embedded: embedded,
    },
      // Tab bar
      React.createElement('div', { style: tabBarStyle },
        tabs.map(t =>
          React.createElement('button', {
            key: t.id,
            style: tabBtnStyle(activeTab === t.id),
            onClick: () => setActiveTab(t.id),
          }, t.label + ' ' + t.trades.length)
        )
      ),

      // Summary cards
      React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 14 } },
        React.createElement('div', { style: { borderRadius: 18, padding: '12px 14px', background: 'linear-gradient(145deg,rgba(255,255,255,0.12),rgba(255,255,255,0.045))', border: '1px solid rgba(255,255,255,0.1)' } },
          React.createElement('div', { style: { fontSize: 10, fontWeight: 900, letterSpacing: 1, opacity: 0.56, textTransform: 'uppercase' } }, 'Total P/L'),
          React.createElement('div', { style: { marginTop: 6, fontSize: 16, fontWeight: 900, letterSpacing: -0.5, color: totalPnl >= 0 ? '#34d399' : '#fb7185', fontVariantNumeric: 'tabular-nums' } },
            fmtTotal(totalPnl, currency))
        ),
        React.createElement('div', { style: { borderRadius: 18, padding: '12px 14px', background: 'linear-gradient(145deg,rgba(255,255,255,0.12),rgba(255,255,255,0.045))', border: '1px solid rgba(255,255,255,0.1)' } },
          React.createElement('div', { style: { fontSize: 10, fontWeight: 900, letterSpacing: 1, opacity: 0.56, textTransform: 'uppercase' } }, 'Win Rate'),
          React.createElement('div', { style: { marginTop: 6, fontSize: 16, fontWeight: 900, letterSpacing: -0.5, color: wr >= 45 ? '#34d399' : wr >= 39 ? '#fbbf24' : '#fb7185' } }, wr + '%')
        ),
        React.createElement('div', { style: { borderRadius: 18, padding: '12px 14px', background: 'linear-gradient(145deg,rgba(255,255,255,0.12),rgba(255,255,255,0.045))', border: '1px solid rgba(255,255,255,0.1)' } },
          React.createElement('div', { style: { fontSize: 10, fontWeight: 900, letterSpacing: 1, opacity: 0.56, textTransform: 'uppercase' } }, 'W / L'),
          React.createElement('div', { style: { marginTop: 6, fontSize: 16, fontWeight: 900, letterSpacing: -0.5 } },
            React.createElement('span', { style: { color: '#34d399' } }, wins.length),
            React.createElement('span', { style: { opacity: 0.4, margin: '0 3px' } }, '/'),
            React.createElement('span', { style: { color: '#fb7185' } }, losses.length)
          )
        )
      ),

      // Trade list
      trades.length === 0
        ? React.createElement('div', { style: { textAlign: 'center', padding: '40px 0', opacity: 0.5, fontSize: 14 } }, 'まだ取引履歴がありません')
        : React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
            trades.map(function(tr, i) {
              const pnlRaw = currency === 'usd' ? tr.pnl_usd : tr.pnl_jpy;
              const pnl = Number(pnlRaw) || 0;
              const isWin = pnl > 0;
              const isLoss = pnl < 0;
              return React.createElement('div', {
                key: tr.pos_id || i,
                style: {
                  borderRadius: 18, padding: '12px 14px',
                  background: 'linear-gradient(145deg,rgba(255,255,255,0.10),rgba(255,255,255,0.038))',
                  border: '1px solid ' + (isWin ? 'rgba(52,211,153,0.22)' : isLoss ? 'rgba(251,113,133,0.22)' : 'rgba(255,255,255,0.09)'),
                }
              },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 } },
                  React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 } },
                    React.createElement('span', {
                      style: { fontSize: 10, fontWeight: 900, letterSpacing: 0.8, padding: '3px 8px', borderRadius: 7, flexShrink: 0,
                        background: tr.side === 'BUY' ? 'rgba(96,165,250,0.2)' : 'rgba(251,191,36,0.2)',
                        color: tr.side === 'BUY' ? '#60a5fa' : '#fbbf24' }
                    }, tr.side || '-'),
                    React.createElement('span', {
                      style: { fontSize: 10, fontWeight: 900, letterSpacing: 0.6, padding: '3px 8px', borderRadius: 7, flexShrink: 0,
                        background: exitColor(tr.exit_reason) + '22', color: exitColor(tr.exit_reason) }
                    }, exitLabel(tr.exit_reason)),
                    tr.symbol && React.createElement('span', {
                      style: { fontSize: 10, fontWeight: 800, padding: '3px 7px', borderRadius: 7, flexShrink: 0,
                        background: 'rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.7)' }
                    }, tr.symbol),
                    React.createElement('span', { style: { fontSize: 11, opacity: 0.52, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
                      fmtTime(tr.time))
                  ),
                  React.createElement('div', {
                    style: { fontSize: 15, fontWeight: 900, letterSpacing: -0.5, flexShrink: 0, fontVariantNumeric: 'tabular-nums',
                      color: isWin ? '#34d399' : isLoss ? '#fb7185' : '#94a3b8' }
                  }, fmtPnl(tr, currency))
                ),
                React.createElement('div', { style: { marginTop: 6, display: 'flex', gap: 8, fontSize: 11, opacity: 0.52, fontVariantNumeric: 'tabular-nums' } },
                  React.createElement('span', null, fmtPrice(tr.entry_price, currency)),
                  React.createElement('span', null, '→'),
                  React.createElement('span', null, fmtPrice(tr.exit_price, currency)),
                  tr.ret_pct != null && React.createElement('span', { style: { marginLeft: 'auto', color: isWin ? '#34d399' : '#fb7185' } },
                    (tr.ret_pct >= 0 ? '+' : '') + Number(tr.ret_pct).toFixed(3) + '%')
                )
              );
            })
          )
    )
  );
}
