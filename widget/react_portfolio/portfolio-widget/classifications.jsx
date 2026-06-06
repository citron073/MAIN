// Additional classifications — industry, region, asset class derived from holdings.

const SYMBOL_META = {
  // ── US equities ─────────────────────────
  NVDA:    { industry: 'Semiconductors',     region: 'US',     asset: 'Equity' },
  AVGO:    { industry: 'Semiconductors',     region: 'US',     asset: 'Equity' },
  AAPL:    { industry: 'Consumer Hardware',  region: 'US',     asset: 'Equity' },
  MSFT:    { industry: 'Software',           region: 'US',     asset: 'Equity' },
  GOOG:    { industry: 'Internet Media',     region: 'US',     asset: 'Equity' },
  AMZN:    { industry: 'E-commerce',         region: 'US',     asset: 'Equity' },
  JPM:     { industry: 'Banks',              region: 'US',     asset: 'Equity' },
  'BRK.B': { industry: 'Holding Co.',        region: 'US',     asset: 'Equity' },
  V:       { industry: 'Payments',           region: 'US',     asset: 'Equity' },
  LLY:     { industry: 'Pharma',             region: 'US',     asset: 'Equity' },
  UNH:     { industry: 'Health Insurance',   region: 'US',     asset: 'Equity' },
  COST:    { industry: 'Retail',             region: 'US',     asset: 'Equity' },
  XOM:     { industry: 'Oil Major',          region: 'US',     asset: 'Equity' },
  VTI:     { industry: 'Broad ETF',          region: 'Global', asset: 'ETF' },
  // ── Crypto ──────────────────────────────
  BTC:     { industry: 'Bitcoin',            region: 'Crypto', asset: 'Crypto Major' },
  ETH:     { industry: 'Ethereum',           region: 'Crypto', asset: 'Crypto Major' },
  SOL:     { industry: 'L1 Alt',             region: 'Crypto', asset: 'Crypto L1' },
  BNB:     { industry: 'Exchange Token',     region: 'Crypto', asset: 'Crypto Major' },
  LINK:    { industry: 'Oracle',             region: 'Crypto', asset: 'Crypto Alt' },
  AVAX:    { industry: 'L1 Alt',             region: 'Crypto', asset: 'Crypto L1' },
  MATIC:   { industry: 'L2',                 region: 'Crypto', asset: 'Crypto Alt' },
  TON:     { industry: 'L1 Alt',             region: 'Crypto', asset: 'Crypto L1' },
  DOGE:    { industry: 'Meme',               region: 'Crypto', asset: 'Crypto Alt' },
};

// Extend SECTOR_COLORS with industry/region/asset palettes
Object.assign(SECTOR_COLORS, {
  'Semiconductors':   '#7E5BFF',
  'Software':         '#4A8BFF',
  'Internet Media':   '#3CD4E3',
  'E-commerce':       '#FF9D42',
  'Consumer Hardware':'#EE5C8E',
  'Banks':            '#F0B23C',
  'Holding Co.':      '#B98E61',
  'Payments':         '#19C39A',
  'Pharma':           '#16C784',
  'Health Insurance': '#0EA888',
  'Retail':           '#FF6A8A',
  'Oil Major':        '#E8743B',
  'Broad ETF':        '#8C9AAB',
  'Bitcoin':          '#F7931A',
  'Ethereum':         '#8A92B2',
  'L1 Alt':           '#9945FF',
  'L2':               '#A87DFF',
  'Oracle':           '#2B5CFF',
  'Exchange Token':   '#F0B90B',
  'Meme':             '#FF6B3B',
  // regions
  'US':               '#3B82F6',
  'Europe':           '#19C39A',
  'Japan':            '#EA3943',
  'Emerging Mkt':     '#F0B23C',
  'Crypto':           '#F7931A',
  'Global':           '#6C7891',
  // asset classes
  'Equity':           '#3B82F6',
  'ETF':              '#5DA8FF',
  'Crypto Major':     '#F7931A',
  'Crypto L1':        '#9945FF',
  'Crypto Alt':       '#26A17B',
  'Other':            '#9aa3b2',
});

const CLASSIFICATION_LABELS = {
  sector:    'Sector',
  industry:  'Industry',
  region:    'Region',
  asset:     'Asset Class',
};

function getBreakdown(account, classification) {
  if (classification === 'sector' || !classification) return account.sectors;

  const map = {};
  for (const h of account.holdings) {
    const meta = SYMBOL_META[h.ticker] || {};
    const key = meta[classification] || 'Other';
    map[key] = (map[key] || 0) + h.value;
  }
  if (account.cash > 0 && classification === 'asset') {
    map['Cash'] = (map['Cash'] || 0) + account.cash;
  }
  return Object.entries(map)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}

function classificationTitle(classification) {
  return CLASSIFICATION_LABELS[classification] || 'Allocation';
}

Object.assign(window, { SYMBOL_META, CLASSIFICATION_LABELS, getBreakdown, classificationTitle });
