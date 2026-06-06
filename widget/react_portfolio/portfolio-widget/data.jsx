// Mock portfolio data — 4 accounts mixing US equities and crypto.
// All values in USD. P/L deterministic so totals add up cleanly.

const SECTOR_COLORS = {
  Tech:         '#4A8BFF',
  Semis:        '#7E5BFF',
  Finance:      '#F0B23C',
  Health:       '#19C39A',
  Consumer:     '#EE5C8E',
  Energy:       '#E8743B',
  Industrials:  '#8C9AAB',
  Comm:         '#3CD4E3',
  REIT:         '#B98E61',
  'BTC':        '#F7931A',
  'ETH':        '#8A92B2',
  'SOL':        '#14F195',
  'L1/L2 Alt':  '#9945FF',
  'Stable':     '#26A17B',
  Cash:         '#9aa3b2',
};

// 60-day sparkline generator — deterministic per seed
function spark(seed, len = 60, vol = 0.012, drift = 0.0008) {
  const r = (n) => { const x = Math.sin(seed * 9301 + n * 49297) * 233280; return x - Math.floor(x); };
  const out = [1];
  for (let i = 1; i < len; i++) {
    const step = (r(i) - 0.5) * vol + drift;
    out.push(out[i - 1] * (1 + step));
  }
  return out;
}

const ACCOUNTS = [
  {
    id: 'robinhood',
    name: 'Robinhood',
    short: 'RH',
    type: 'US Equities',
    brandColor: '#00C805',
    value: 87420.55,
    cash: 1840.22,
    todayPL: 1247.30,
    todayPLPct: 1.45,
    weekPLPct: 3.21,
    ytdPLPct: 24.8,
    sparkline: spark(11, 60, 0.014, 0.0011),
    sectors: [
      { name: 'Semis',       value: 22310 },
      { name: 'Tech',        value: 18200 },
      { name: 'Consumer',    value: 11240 },
      { name: 'Finance',     value:  9820 },
      { name: 'Health',      value:  8430 },
      { name: 'Comm',        value:  6850 },
      { name: 'Industrials', value:  5320 },
      { name: 'Energy',      value:  3410 },
      { name: 'Cash',        value:  1840.55 },
    ],
    holdings: [
      { ticker: 'NVDA', name: 'NVIDIA',     value: 14820, w: 16.95, plPct:  2.81 },
      { ticker: 'AAPL', name: 'Apple',      value:  9240, w: 10.57, plPct:  0.42 },
      { ticker: 'AMZN', name: 'Amazon',     value:  7180, w:  8.21, plPct:  1.18 },
      { ticker: 'AVGO', name: 'Broadcom',   value:  6420, w:  7.34, plPct:  3.12 },
      { ticker: 'JPM',  name: 'JPMorgan',   value:  5240, w:  5.99, plPct: -0.43 },
      { ticker: 'LLY',  name: 'Eli Lilly',  value:  4820, w:  5.51, plPct:  1.92 },
      { ticker: 'GOOG', name: 'Alphabet',   value:  4380, w:  5.01, plPct: -0.84 },
    ],
  },
  {
    id: 'schwab',
    name: 'Schwab',
    short: 'SC',
    type: 'IRA / Long-term',
    brandColor: '#00A0DF',
    value: 142810.20,
    cash: 5210.45,
    todayPL: -384.20,
    todayPLPct: -0.27,
    weekPLPct: 1.05,
    ytdPLPct: 14.2,
    sparkline: spark(23, 60, 0.009, 0.0006),
    sectors: [
      { name: 'Tech',        value: 38420 },
      { name: 'Finance',     value: 24210 },
      { name: 'Health',      value: 21430 },
      { name: 'Industrials', value: 15820 },
      { name: 'Consumer',    value: 12820 },
      { name: 'Energy',      value: 10240 },
      { name: 'REIT',        value:  8210 },
      { name: 'Comm',        value:  6450 },
      { name: 'Cash',        value:  5210.20 },
    ],
    holdings: [
      { ticker: 'VTI',  name: 'Vanguard Total',   value: 31200, w: 21.85, plPct: -0.18 },
      { ticker: 'MSFT', name: 'Microsoft',        value: 18420, w: 12.90, plPct:  0.31 },
      { ticker: 'BRK.B',name: 'Berkshire B',      value: 11280, w:  7.90, plPct: -0.42 },
      { ticker: 'UNH',  name: 'UnitedHealth',     value:  9210, w:  6.45, plPct: -1.10 },
      { ticker: 'COST', name: 'Costco',           value:  7420, w:  5.20, plPct:  0.84 },
      { ticker: 'XOM',  name: 'Exxon',            value:  6420, w:  4.50, plPct: -0.95 },
      { ticker: 'V',    name: 'Visa',             value:  5240, w:  3.67, plPct:  0.12 },
    ],
  },
  {
    id: 'coinbase',
    name: 'Coinbase',
    short: 'CB',
    type: 'Crypto',
    brandColor: '#1652F0',
    value: 38245.18,
    cash: 420.30,
    todayPL: 942.15,
    todayPLPct: 2.52,
    weekPLPct: -2.84,
    ytdPLPct: 58.4,
    sparkline: spark(37, 60, 0.028, 0.0016),
    sectors: [
      { name: 'BTC',       value: 19820 },
      { name: 'ETH',       value:  9420 },
      { name: 'SOL',       value:  4820 },
      { name: 'L1/L2 Alt', value:  3160 },
      { name: 'Stable',    value:   605.18 },
      { name: 'Cash',      value:   420 },
    ],
    holdings: [
      { ticker: 'BTC',  name: 'Bitcoin',     value: 19820, w: 51.83, plPct:  1.84 },
      { ticker: 'ETH',  name: 'Ethereum',    value:  9420, w: 24.63, plPct:  2.95 },
      { ticker: 'SOL',  name: 'Solana',      value:  4820, w: 12.60, plPct:  4.21 },
      { ticker: 'LINK', name: 'Chainlink',   value:  1480, w:  3.87, plPct:  1.12 },
      { ticker: 'AVAX', name: 'Avalanche',   value:   980, w:  2.56, plPct: -0.84 },
      { ticker: 'MATIC',name: 'Polygon',     value:   700, w:  1.83, plPct: -1.20 },
    ],
  },
  {
    id: 'binance',
    name: 'Binance',
    short: 'BN',
    type: 'Crypto (Intl)',
    brandColor: '#F0B90B',
    value: 24580.40,
    cash: 1200.10,
    todayPL: -512.84,
    todayPLPct: -2.04,
    weekPLPct: 4.12,
    ytdPLPct: 82.1,
    sparkline: spark(53, 60, 0.034, 0.0021),
    sectors: [
      { name: 'BTC',       value:  8420 },
      { name: 'ETH',       value:  5820 },
      { name: 'L1/L2 Alt', value:  6420 },
      { name: 'SOL',       value:  2120 },
      { name: 'Stable',    value:   600 },
      { name: 'Cash',      value:  1200.40 },
    ],
    holdings: [
      { ticker: 'BTC',   name: 'Bitcoin',     value: 8420, w: 34.25, plPct: -1.32 },
      { ticker: 'ETH',   name: 'Ethereum',    value: 5820, w: 23.68, plPct: -2.85 },
      { ticker: 'BNB',   name: 'BNB',         value: 3210, w: 13.06, plPct: -1.42 },
      { ticker: 'SOL',   name: 'Solana',      value: 2120, w:  8.62, plPct: -0.84 },
      { ticker: 'TON',   name: 'Toncoin',     value: 1820, w:  7.40, plPct:  2.12 },
      { ticker: 'DOGE',  name: 'Dogecoin',    value:  840, w:  3.42, plPct: -4.20 },
    ],
  },
];

// "All" — aggregate view
function aggregateAccounts(accounts) {
  const totalValue = accounts.reduce((s, a) => s + a.value, 0);
  const totalPL    = accounts.reduce((s, a) => s + a.todayPL, 0);
  const todayPLPct = (totalPL / (totalValue - totalPL)) * 100;

  // Sum sectors across accounts
  const secMap = {};
  for (const a of accounts) {
    for (const s of a.sectors) {
      secMap[s.name] = (secMap[s.name] || 0) + s.value;
    }
  }
  const sectors = Object.entries(secMap)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  // top holdings — flatten + sort by value
  const holdings = accounts
    .flatMap(a => a.holdings.map(h => ({ ...h, account: a.short })))
    .sort((a, b) => b.value - a.value)
    .slice(0, 12);

  // Aggregate sparkline — average normalized
  const len = accounts[0].sparkline.length;
  const sparkline = Array.from({ length: len }, (_, i) => {
    return accounts.reduce((s, a) => s + a.sparkline[i] * a.value, 0)
         / accounts.reduce((s, a) => s + a.value, 0);
  });

  return {
    id: 'all',
    name: 'All Accounts',
    short: 'Σ',
    type: `${accounts.length} accounts`,
    brandColor: '#ffffff',
    value: totalValue,
    cash: accounts.reduce((s, a) => s + a.cash, 0),
    todayPL: totalPL,
    todayPLPct,
    weekPLPct: accounts.reduce((s, a) => s + a.weekPLPct * a.value, 0) / totalValue,
    ytdPLPct:  accounts.reduce((s, a) => s + a.ytdPLPct  * a.value, 0) / totalValue,
    sparkline,
    sectors,
    holdings,
  };
}

Object.assign(window, { ACCOUNTS, SECTOR_COLORS, aggregateAccounts });
