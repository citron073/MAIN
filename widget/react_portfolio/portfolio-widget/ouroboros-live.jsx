// Ouroboros live-data bridge.
// Keeps the ZIP React UI intact, but replaces mock accounts with widget-status.json.

(function () {
  const params = new URLSearchParams(window.location.search);
  const token = params.get('token') || '';
  const suffix = token ? ('?token=' + encodeURIComponent(token)) : '';
  const listeners = new Set();

  window.OUROBOROS_CURRENCY = 'JPY';
  window.OUROBOROS_LIVE_STATUS = null;
  window.OUROBOROS_LIVE_ACCOUNTS = null;

  const n = (v, d = 0) => {
    const x = Number(v);
    return Number.isFinite(x) ? x : d;
  };
  const b = (v) => Boolean(v);
  const pct = (part, total) => {
    const denom = Math.abs(n(total, 0));
    return denom > 0 ? (n(part, 0) / denom) * 100 : 0;
  };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const yen = (v) => Math.max(0, Math.abs(n(v, 0)));

  function spark(seed, len = 60, drift = 0) {
    const out = [];
    let cur = 1;
    for (let i = 0; i < len; i += 1) {
      const wave = Math.sin((seed + 1) * 0.73 + i * 0.31) * 0.004;
      cur = Math.max(0.72, cur * (1 + wave + drift / len / 100));
      out.push(cur);
    }
    return out;
  }

  function driftColor(status) {
    const s = String(status || '').toUpperCase();
    if (s === 'NORMAL') return '#16C784';
    if (s === 'ALERT') return '#EA3943';
    if (s === 'PAUSED') return '#8C9AAB';
    return '#F0B23C';
  }

  function buildHolding(ticker, name, value, weight, plPct) {
    return { ticker, name, value: yen(value), w: n(weight, 0), plPct: n(plPct, 0) };
  }

  function mapStatusToAccounts(status) {
    const balance = status && status.balance ? status.balance : {};
    const bitflyer = status && status.bitflyer_account ? status.bitflyer_account : balance;
    const ibkr = status && status.ibkr_account ? status.ibkr_account : {};
    const goal = status && status.goal ? status.goal : {};
    const weekly = status && status.weekly ? status.weekly : {};
    const drift = status && status.drift ? status.drift : {};
    const latest = status && status.latest_trade ? status.latest_trade : {};
    const pnlCurve = status && status.pnl_curve ? status.pnl_curve : {};
    const reflection = status && status.latest_reflection ? status.latest_reflection : {};
    const warnings = Array.isArray(status && status.warnings) ? status.warnings : [];

    const ibkrAvailable = b(ibkr.available) && n(ibkr.net_liquidation_jpy, 0) > 0;
    const bitflyerAvailable = b(bitflyer.available) && n(bitflyer.jpy, 0) > 0;
    const balanceAvailable = b(balance.available) && n(balance.jpy, 0) > 0;
    const primaryAvailable = ibkrAvailable || bitflyerAvailable || balanceAvailable;
    const primaryValueRaw = ibkrAvailable ? ibkr.net_liquidation_jpy : (bitflyerAvailable ? bitflyer.jpy : (balanceAvailable ? balance.jpy : null));
    const primaryCashRaw = ibkrAvailable ? ibkr.available_funds_jpy : (bitflyerAvailable ? (bitflyer.jpy_balance || bitflyer.jpy) : (balanceAvailable ? balance.jpy : null));
    const balanceJpy = primaryAvailable ? yen(primaryValueRaw) : null;
    const cashJpy = primaryAvailable ? yen(primaryCashRaw) : null;
    const positionJpy = yen(ibkrAvailable ? Math.abs(n(ibkr.gross_position_value_jpy, 0)) : 0);
    const balanceBase = Math.max(1, n(balanceJpy, 0));
    const accountName = ibkrAvailable ? 'IBKR' : (bitflyerAvailable ? 'bitFlyer' : '口座未取得');
    const accountShort = ibkrAvailable ? 'IB' : (bitflyerAvailable ? 'BF' : 'NA');
    const accountType = ibkrAvailable
      ? `${String(ibkr.account_id || 'IBKR')} / ${ibkr.stale ? 'STALE' : 'LIVE'}`
      : (bitflyerAvailable
        ? `${String(bitflyer.label || 'bitFlyer')} / ${String(bitflyer.source || 'LIVE')}`
        : `bitFlyer ${String(bitflyer.error || balance.error || '未取得')} / ${status.mode_label || '-'}`);
    const todayPnl = n(goal.pnl_jpy, n(status && status.daily_pnl_jpy, 0));
    const goalJpy = Math.max(1, yen(goal.goal_jpy || 100));
    const weeklyPnl = n(weekly.pnl_jpy_sum, 0);
    const closedN = n(weekly.closed_n, 0);
    const driftRemain = n(drift.remaining_samples, 0);
    const latestPnl = n(latest.pnl_jpy, 0);
    const pnlPoints = Array.isArray(pnlCurve.points) ? pnlCurve.points.map(v => Number(v)).filter(Number.isFinite) : [];
    const pnlBars = Array.isArray(pnlCurve.bars) ? pnlCurve.bars.map(v => Number(v)).filter(Number.isFinite) : [];
    const accountSparkline = pnlPoints.length >= 2 ? pnlPoints : spark(11, 60, pct(weeklyPnl, balanceBase));
    const warnWeight = warnings.length ? Math.min(40, warnings.length * 10) : 5;
    const okWeight = Math.max(10, 100 - warnWeight);
    const statusValue = b(status && status.trade_enabled) && b(status && status.runner_alive) ? 100 : 55;

    return [
      {
        id: 'robinhood',
        name: accountName,
        short: accountShort,
        type: accountType,
        brandColor: '#16C784',
        value: balanceJpy,
        cash: cashJpy,
        valueMissing: !primaryAvailable,
        missingReason: primaryAvailable ? '' : String(bitflyer.setup_hint || bitflyer.error || balance.error || 'account unavailable'),
        todayPL: todayPnl,
        todayPLPct: pct(todayPnl, balanceBase),
        weekPLPct: pct(weeklyPnl, balanceBase),
        ytdPLPct: pct(weeklyPnl + todayPnl, balanceBase),
        sparkline: accountSparkline,
        pnlCurve: pnlPoints,
        pnlBars,
        pnlStats: {
          available: b(pnlCurve.available),
          closedN: n(pnlCurve.closed_n, pnlBars.length),
          totalPnl: n(pnlCurve.total_pnl_jpy, pnlBars.reduce((s, v) => s + v, 0)),
          winRate: n(pnlCurve.win_rate_pct, 0),
          avgPnl: n(pnlCurve.avg_pnl_jpy, 0),
          bestPnl: n(pnlCurve.best_pnl_jpy, 0),
          worstPnl: n(pnlCurve.worst_pnl_jpy, 0),
          source: String(pnlCurve.source || 'recent_trades'),
        },
        sectors: [
          { name: 'Cash', value: cashJpy },
          { name: 'Position', value: positionJpy },
          { name: 'Health', value: okWeight },
          { name: 'Energy', value: warnWeight },
        ],
        holdings: [
          buildHolding(ibkrAvailable ? 'NLV' : (bitflyerAvailable ? 'BF' : 'NA'), ibkrAvailable ? 'IBKR NetLiq' : (bitflyerAvailable ? String(bitflyer.label || 'bitFlyer') : 'Account not loaded'), balanceJpy || 0, 100, pct(todayPnl, balanceBase)),
          buildHolding('CASH', ibkrAvailable ? 'Available Funds' : (bitflyerAvailable ? 'JPY Balance' : 'Cash'), cashJpy || 0, 0, pct(cashJpy || 0, balanceBase)),
          buildHolding('DAY', 'Daily PnL', Math.abs(todayPnl), 0, pct(todayPnl, balanceBase)),
          buildHolding('WEEK', 'Weekly PnL', Math.abs(weeklyPnl), 0, pct(weeklyPnl, balanceBase)),
          buildHolding('RUN', b(status.runner_alive) ? 'Runner ON' : 'Runner OFF', statusValue, 0, b(status.runner_alive) ? 1 : -1),
        ],
      },
      {
        id: 'schwab',
        name: 'Daily Goal',
        short: 'DG',
        type: goal.achieved ? 'Goal achieved' : 'Goal tracking',
        brandColor: '#4A8BFF',
        value: goalJpy,
        cash: yen(goal.remaining_jpy),
        todayPL: todayPnl,
        todayPLPct: pct(todayPnl, goalJpy),
        weekPLPct: pct(todayPnl, goalJpy),
        ytdPLPct: pct(todayPnl, goalJpy),
        sparkline: spark(23, 60, pct(todayPnl, goalJpy)),
        sectors: [
          { name: 'Tech', value: clamp(Math.max(0, todayPnl), 1, goalJpy) },
          { name: 'Cash', value: clamp(yen(goal.remaining_jpy), 1, goalJpy) },
        ],
        holdings: [
          buildHolding('GOAL', 'Daily Goal', goalJpy, 100, pct(todayPnl, goalJpy)),
          buildHolding('PNL', 'Current PnL', Math.abs(todayPnl), 0, pct(todayPnl, goalJpy)),
          buildHolding('CLOSE', `${n(goal.closed_n, 0)} closed`, n(goal.closed_n, 0) * 1000, 0, n(goal.closed_n, 0)),
        ],
      },
      {
        id: 'coinbase',
        name: 'Weekly',
        short: 'WK',
        type: `${closedN} closed / WR ${n(weekly.win_rate_pct, 0).toFixed(1)}%`,
        brandColor: '#F0B23C',
        value: Math.max(1000, Math.abs(weeklyPnl) + closedN * 1000),
        cash: closedN * 1000,
        todayPL: weeklyPnl,
        todayPLPct: pct(weeklyPnl, balanceBase),
        weekPLPct: pct(weeklyPnl, balanceBase),
        ytdPLPct: n(weekly.win_rate_pct, 0),
        sparkline: spark(37, 60, pct(weeklyPnl, balanceBase)),
        sectors: [
          { name: 'Finance', value: Math.max(1, closedN) },
          { name: 'Consumer', value: Math.max(1, 100 - n(weekly.win_rate_pct, 0)) },
          { name: 'Health', value: Math.max(1, n(weekly.win_rate_pct, 0)) },
        ],
        holdings: [
          buildHolding('PNL', 'Weekly PnL', Math.abs(weeklyPnl), 0, pct(weeklyPnl, balanceBase)),
          buildHolding('WR', 'Win Rate', n(weekly.win_rate_pct, 0) * 100, 0, n(weekly.win_rate_pct, 0)),
          buildHolding('CLS', 'Closed Trades', closedN * 1000, 0, closedN),
        ],
      },
      {
        id: 'binance',
        name: 'Ops',
        short: 'OP',
        type: `${String(drift.status || '-')} / ${status.status_level || '-'}`,
        brandColor: driftColor(drift.status),
        value: Math.max(1000, statusValue * 1000),
        cash: driftRemain * 1000,
        todayPL: b(status.runner_alive) ? 0 : -1000,
        todayPLPct: b(status.runner_alive) ? 0 : -10,
        weekPLPct: warnings.length ? -warnings.length : 1,
        ytdPLPct: b(reflection.available) ? 1 : 0,
        sparkline: spark(53, 60, warnings.length ? -2 : 2),
        sectors: [
          { name: 'Health', value: okWeight },
          { name: 'Energy', value: warnWeight },
          { name: 'Industrials', value: Math.max(1, driftRemain) },
        ],
        holdings: [
          buildHolding('DRIFT', String(drift.status || 'Drift'), Math.max(1, driftRemain) * 1000, 0, drift.resume_ready ? 1 : -1),
          buildHolding('LATEST', String(latest.reason || 'Latest'), Math.abs(latestPnl), 0, latestPnl),
          buildHolding('WARN', `${warnings.length} warnings`, warnings.length * 1000, 0, -warnings.length),
        ],
      },
    ];
  }

  function publish(status) {
    const accounts = mapStatusToAccounts(status);
    window.OUROBOROS_LIVE_STATUS = status;
    window.OUROBOROS_LIVE_ACCOUNTS = accounts;
    for (const fn of listeners) {
      try { fn(status, accounts); } catch {}
    }
  }

  async function refresh() {
    try {
      const res = await fetch('/widget-status.json' + suffix, { cache: 'no-store' });
      if (!res.ok) throw new Error('widget-status HTTP ' + res.status);
      publish(await res.json());
    } catch (err) {
      console.warn('Ouroboros live data unavailable', err);
    }
  }

  window.OUROBOROS_LIVE = {
    refresh,
    subscribe(fn) {
      listeners.add(fn);
      if (window.OUROBOROS_LIVE_STATUS && window.OUROBOROS_LIVE_ACCOUNTS) {
        fn(window.OUROBOROS_LIVE_STATUS, window.OUROBOROS_LIVE_ACCOUNTS);
      }
      return () => listeners.delete(fn);
    },
  };

  refresh();
  window.setInterval(refresh, 60000);
})();
