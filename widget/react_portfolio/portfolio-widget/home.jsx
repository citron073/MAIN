// iPhone home-screen container — wallpaper, status bar, widget grid with drag-to-rearrange.

const HOME_BG_LIGHT = `radial-gradient(120% 80% at 20% 0%, #d9e1f5 0%, #c9d4eb 35%, #b3c0dc 65%, #9eaecc 100%)`;
const HOME_BG_DARK  = `radial-gradient(140% 100% at 30% 0%, #1d2742 0%, #14182a 40%, #0a0d18 70%, #050609 100%)`;

// ─── Status bar ────────────────────────────────────────────────────────
function StatusBar({ dark }) {
  const c = dark ? '#fff' : '#000';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '14px 30px 0', height: 54, boxSizing: 'border-box',
      color: c, fontFamily: '-apple-system, system-ui', fontWeight: 600, fontSize: 16,
      position: 'relative', zIndex: 5,
    }}>
      <div style={{ fontVariantNumeric: 'tabular-nums' }}>9:41</div>
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        {/* signal */}
        <svg width="17" height="11" viewBox="0 0 17 11">
          <rect x="0" y="6" width="3" height="4" rx="0.6" fill={c}/>
          <rect x="4.5" y="4" width="3" height="6" rx="0.6" fill={c}/>
          <rect x="9" y="2" width="3" height="8" rx="0.6" fill={c}/>
          <rect x="13.5" y="0" width="3" height="10" rx="0.6" fill={c}/>
        </svg>
        {/* wifi */}
        <svg width="16" height="11" viewBox="0 0 16 11">
          <path d="M8 2.5C10.2 2.5 12.2 3.4 13.6 4.8L14.7 3.8C13 2.1 10.6 1 8 1S3 2.1 1.3 3.8L2.4 4.8C3.8 3.4 5.8 2.5 8 2.5z" fill={c}/>
          <path d="M8 5.8C9.3 5.8 10.5 6.3 11.4 7.2L12.5 6.1C11.3 4.9 9.7 4.2 8 4.2S4.7 4.9 3.5 6.1L4.6 7.2C5.5 6.3 6.7 5.8 8 5.8z" fill={c}/>
          <circle cx="8" cy="9.5" r="1.3" fill={c}/>
        </svg>
        {/* battery */}
        <svg width="25" height="12" viewBox="0 0 25 12">
          <rect x="0.5" y="0.5" width="22" height="11" rx="3" stroke={c} strokeOpacity="0.4" fill="none"/>
          <rect x="2" y="2" width="19" height="8" rx="1.5" fill={c}/>
          <path d="M23.5 4v4c.7-.2 1.2-1 1.2-2s-.5-1.8-1.2-2z" fill={c} fillOpacity="0.4"/>
        </svg>
      </div>
    </div>
  );
}

// ─── App icon (placeholder for the dock) ───────────────────────────────
function AppIcon({ label, color, glyph, dark }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, width: 60 }}>
      <div style={{
        width: 56, height: 56, borderRadius: 14, background: color,
        boxShadow: '0 4px 10px rgba(0,0,0,0.3), inset 0 0.5px 0 rgba(255,255,255,0.2)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#fff', fontWeight: 700, fontSize: 22, letterSpacing: -0.5,
      }}>{glyph}</div>
      <div style={{
        fontSize: 11, color: dark ? '#fff' : '#fff', fontWeight: 500,
        textShadow: '0 1px 2px rgba(0,0,0,0.4)',
        fontFamily: '-apple-system, system-ui',
      }}>{label}</div>
    </div>
  );
}

// ─── Edit-mode wiggle ──────────────────────────────────────────────────
const wiggleCSS = `
@keyframes pw-wiggle-a { 0%,100%{transform:rotate(-0.6deg)} 50%{transform:rotate(0.6deg)} }
@keyframes pw-wiggle-b { 0%,100%{transform:rotate(0.6deg)} 50%{transform:rotate(-0.6deg)} }
.pw-wiggle-a { animation: pw-wiggle-a 0.18s ease-in-out infinite; transform-origin: center; }
.pw-wiggle-b { animation: pw-wiggle-b 0.22s ease-in-out infinite; transform-origin: center; }
.pw-pop-enter { animation: pw-pop 0.28s cubic-bezier(0.34,1.56,0.64,1) both; }
@keyframes pw-pop { from { opacity: 0; transform: scale(0.85) } to { opacity: 1; transform: scale(1) } }
.pw-drag { transition: transform 0.22s cubic-bezier(0.2,0.7,0.2,1); }
`;

// ─── Remove button (edit mode) ─────────────────────────────────────────
function RemoveBtn({ onClick }) {
  return (
    <button onClick={(e) => { e.stopPropagation(); onClick(); }} style={{
      position: 'absolute', top: -6, left: -6, width: 22, height: 22,
      borderRadius: '50%', background: 'rgba(40,40,40,0.95)', border: 'none',
      color: '#fff', fontSize: 18, fontWeight: 700, lineHeight: '20px', cursor: 'pointer',
      boxShadow: '0 2px 6px rgba(0,0,0,0.3), inset 0 0.5px 0 rgba(255,255,255,0.15)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 20, padding: 0,
    }}>−</button>
  );
}

// ─── Resize bubble (edit mode, bottom-right) ───────────────────────────
function ResizeBtn({ onClick, current }) {
  return (
    <button onClick={(e) => { e.stopPropagation(); onClick(); }} style={{
      position: 'absolute', bottom: -6, right: -6, height: 22, minWidth: 22, padding: '0 7px',
      borderRadius: 11, background: 'rgba(40,40,40,0.95)', border: 'none',
      color: '#fff', fontSize: 10, fontWeight: 700, cursor: 'pointer',
      boxShadow: '0 2px 6px rgba(0,0,0,0.3), inset 0 0.5px 0 rgba(255,255,255,0.15)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3,
      zIndex: 20, letterSpacing: 0.2,
    }}>
      <svg width="9" height="9" viewBox="0 0 9 9"><path d="M1 5v3h3M8 4V1H5" stroke="#fff" strokeWidth="1.4" fill="none" strokeLinecap="round"/></svg>
      {current}
    </button>
  );
}

// ─── Widget wrapper — handles size mapping, edit chrome, click ─────────
const WIDGET_SIZES = {
  small:  { w: 162, h: 162 },
  medium: { w: 336, h: 162 },
  large:  { w: 336, h: 336 },
  xl:     { w: 336, h: 510 },
};
const SIZE_ORDER = ['small', 'medium', 'large', 'xl'];

function WidgetSlot({ widget, dark, accent, sectorViz, plFormat, classification, editing, onResize, onRemove, onCycleAccount, onTapHolding, draggable, dragHandlers, isDragging, accounts }) {
  const account = widget.accountId === 'all'
    ? aggregateAccounts(accounts)
    : (accounts.find(a => a.id === widget.accountId) || accounts[0] || aggregateAccounts(accounts));

  const { w, h } = WIDGET_SIZES[widget.size];
  const viz = widget.vizOverride || sectorViz;
  const wiggleClass = editing ? (widget.id.charCodeAt(0) % 2 ? 'pw-wiggle-a' : 'pw-wiggle-b') : '';

  const W =
    widget.size === 'small'  ? WidgetSmall  :
    widget.size === 'medium' ? WidgetMedium :
    widget.size === 'large'  ? WidgetLarge  : WidgetXL;

  return (
    <div className={`${wiggleClass} pw-drag pw-pop-enter`}
         {...(draggable ? dragHandlers : {})}
         style={{
           position: 'relative', width: w, height: h,
           opacity: isDragging ? 0.5 : 1,
           cursor: editing ? 'grab' : 'pointer',
         }}>
      <W account={account} dark={dark} accent={accent}
         sectorViz={viz} plFormat={plFormat} classification={classification}
         w={w} h={h}
         onClick={() => !editing && onCycleAccount()}
         onTapHolding={editing ? null : onTapHolding} />
      {editing && (
        <>
          <RemoveBtn onClick={onRemove} />
          <ResizeBtn onClick={onResize} current={({ small: 'S', medium: 'M', large: 'L', xl: 'XL' })[widget.size]} />
        </>
      )}
    </div>
  );
}

// ─── Home screen ───────────────────────────────────────────────────────
function HomeScreen({
  widgets, setWidgets, dark, accent, sectorViz, plFormat, classification,
  editing, setEditing, accounts, onTapHolding, onOpenAlerts,
}) {
  const [dragIdx, setDragIdx] = React.useState(null);
  const [dragOverIdx, setDragOverIdx] = React.useState(null);

  // group widgets into rows: 2 smalls fit in one row, else full row
  const rows = React.useMemo(() => {
    const out = [];
    let pending = null;
    widgets.forEach((wi, i) => {
      if (wi.size === 'small') {
        if (pending) { out.push({ items: [pending, { ...wi, idx: i }] }); pending = null; }
        else pending = { ...wi, idx: i };
      } else {
        if (pending) { out.push({ items: [pending] }); pending = null; }
        out.push({ items: [{ ...wi, idx: i }] });
      }
    });
    if (pending) out.push({ items: [pending] });
    return out;
  }, [widgets]);

  // drag handlers
  const onDragStart = (idx) => (e) => {
    if (!editing) return;
    setDragIdx(idx);
    try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(idx)); } catch {}
  };
  const onDragOver = (idx) => (e) => {
    if (!editing || dragIdx == null) return;
    e.preventDefault();
    if (idx !== dragOverIdx) setDragOverIdx(idx);
  };
  const onDrop = (idx) => (e) => {
    if (!editing || dragIdx == null) return;
    e.preventDefault();
    const from = dragIdx, to = idx;
    setWidgets(ws => {
      const copy = [...ws];
      const [m] = copy.splice(from, 1);
      copy.splice(to, 0, m);
      return copy;
    });
    setDragIdx(null); setDragOverIdx(null);
  };
  const onDragEnd = () => { setDragIdx(null); setDragOverIdx(null); };

  const cycleSize = (idx) => setWidgets(ws => {
    const c = [...ws];
    const i = SIZE_ORDER.indexOf(c[idx].size);
    c[idx] = { ...c[idx], size: SIZE_ORDER[(i + 1) % SIZE_ORDER.length] };
    return c;
  });
  const cycleAccount = (idx) => setWidgets(ws => {
    const c = [...ws];
    const list = ['all', ...accounts.map(a => a.id)];
    const i = list.indexOf(c[idx].accountId);
    c[idx] = { ...c[idx], accountId: list[(i + 1) % list.length] };
    return c;
  });
  const removeWidget = (idx) => setWidgets(ws => ws.filter((_, i) => i !== idx));
  const addWidget = () => setWidgets(ws => [...ws, {
    id: 'w' + Math.random().toString(36).slice(2, 7),
    size: 'small', accountId: accounts[0].id,
  }]);

  return (
    <div style={{
      width: 402, height: 874, position: 'relative', overflow: 'hidden',
      background: dark ? HOME_BG_DARK : HOME_BG_LIGHT,
      borderRadius: 48, fontFamily: '-apple-system, system-ui',
    }}
      onClick={(e) => {
        // tap background → exit edit mode
        if (editing && e.target === e.currentTarget) setEditing(false);
      }}
      onDoubleClick={() => setEditing(true)}
    >
      <style>{wiggleCSS}</style>

      {/* Dynamic Island */}
      <div style={{
        position: 'absolute', top: 11, left: '50%', transform: 'translateX(-50%)',
        width: 126, height: 37, borderRadius: 24, background: '#000', zIndex: 50,
      }} />

      <StatusBar dark={dark} />

      {/* edit mode hint */}
      {editing && (
        <button onClick={() => setEditing(false)} style={{
          position: 'absolute', top: 12, right: 16, zIndex: 50,
          padding: '5px 14px', borderRadius: 999, border: 'none',
          background: 'rgba(255,255,255,0.95)', color: '#000',
          fontWeight: 600, fontSize: 13, cursor: 'pointer',
          boxShadow: '0 2px 10px rgba(0,0,0,0.15)',
        }}>Done</button>
      )}
      {!editing && onOpenAlerts && (
        <button onClick={onOpenAlerts} style={{
          position: 'absolute', top: 14, right: 18, zIndex: 50,
          width: 32, height: 32, borderRadius: '50%', border: 'none',
          background: 'rgba(255,255,255,0.18)', color: '#fff', cursor: 'pointer',
          backdropFilter: 'blur(20px)', WebkitBackdropFilter: 'blur(20px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: 'inset 0 0.5px 0 rgba(255,255,255,0.2)',
        }} title="Alerts">
          <svg width="14" height="16" viewBox="0 0 14 16" fill="none">
            <path d="M7 1c-2.2 0-4 1.8-4 4v3.2c0 .5-.2 1-.6 1.4L1 11h12l-1.4-1.4c-.4-.4-.6-.9-.6-1.4V5c0-2.2-1.8-4-4-4zM5 13a2 2 0 004 0" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      )}

      {/* Widget grid (scrollable) */}
      <div style={{
        position: 'absolute', top: 54, left: 0, right: 0, bottom: 100,
        overflowY: 'auto', overflowX: 'hidden',
        padding: '8px 24px 16px',
      }}
        onClick={(e) => { if (editing && e.target === e.currentTarget) setEditing(false); }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {rows.map((row, ri) => (
            <div key={ri} style={{
              display: 'flex', gap: 12, justifyContent: row.items.length === 1 ? 'center' : 'space-between',
            }}>
              {row.items.map(item => (
                <WidgetSlot key={item.id}
                  widget={item}
                  dark={dark} accent={accent}
                  sectorViz={sectorViz} plFormat={plFormat} classification={classification}
                  editing={editing}
                  onResize={() => cycleSize(item.idx)}
                  onRemove={() => removeWidget(item.idx)}
                  onCycleAccount={() => cycleAccount(item.idx)}
                  onTapHolding={onTapHolding}
                  draggable={editing}
                  isDragging={dragIdx === item.idx}
                  dragHandlers={{
                    draggable: true,
                    onDragStart: onDragStart(item.idx),
                    onDragOver: onDragOver(item.idx),
                    onDrop: onDrop(item.idx),
                    onDragEnd,
                  }}
                  accounts={accounts}
                />
              ))}
            </div>
          ))}

          {editing && (
            <button onClick={addWidget} style={{
              alignSelf: 'center', marginTop: 4,
              padding: '8px 16px', borderRadius: 999, border: '1px dashed rgba(255,255,255,0.45)',
              background: 'rgba(255,255,255,0.08)', color: '#fff',
              fontSize: 12, fontWeight: 600, cursor: 'pointer', letterSpacing: -0.1,
              fontFamily: '-apple-system, system-ui',
            }}>＋ Add widget</button>
          )}
          {!editing && (
            <div style={{
              textAlign: 'center', marginTop: 4,
              fontSize: 11, color: dark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)',
              letterSpacing: -0.1,
            }}>Long-press · double-tap empty space to edit layout</div>
          )}
        </div>
      </div>

      {/* Dock */}
      <div style={{
        position: 'absolute', bottom: 24, left: 12, right: 12, height: 88,
        background: dark ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.3)',
        backdropFilter: 'blur(20px) saturate(180%)', WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        borderRadius: 32, display: 'flex', alignItems: 'center', justifyContent: 'space-around',
        padding: '0 16px', boxShadow: 'inset 0 0.5px 0 rgba(255,255,255,0.2)',
      }}>
        <AppIcon label="Phone" color="linear-gradient(180deg,#54e667,#1ca72d)" glyph="📞" dark={dark} />
        <AppIcon label="Mail" color="linear-gradient(180deg,#4ea3ff,#1162d1)" glyph="✉" dark={dark} />
        <AppIcon label="Messages" color="linear-gradient(180deg,#54e667,#19a72d)" glyph="💬" dark={dark} />
        <AppIcon label="Bloomberg" color="linear-gradient(180deg,#222,#000)" glyph="B" dark={dark} />
      </div>

      {/* Home indicator */}
      <div style={{
        position: 'absolute', bottom: 8, left: 0, right: 0, height: 5,
        display: 'flex', justifyContent: 'center',
      }}>
        <div style={{
          width: 139, height: 5, borderRadius: 100,
          background: dark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.4)',
        }} />
      </div>
    </div>
  );
}

Object.assign(window, { HomeScreen, WIDGET_SIZES, SIZE_ORDER });
