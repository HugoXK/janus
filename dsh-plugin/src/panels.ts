export interface Panel {
  id: string;
  title: string;
  description: string;
  resource: string;
}

export const panels: Panel[] = [
  {
    id: "market",
    title: "Market",
    description: "Indices, breadth, volatility, liquidity, macro, regime.",
    resource: "janus://calibration",
  },
  {
    id: "sector",
    title: "Sector",
    description: "Relative rotation, momentum, breadth, revisions, flows.",
    resource: "janus://forecasts",
  },
  {
    id: "stock",
    title: "Stock",
    description: "Trend, momentum, volatility, volume, fundamentals, events.",
    resource: "janus://theses",
  },
  {
    id: "thesis",
    title: "Thesis",
    description: "Beliefs, assumptions, catalysts, risks, falsifiers.",
    resource: "janus://theses",
  },
  {
    id: "calibration",
    title: "Calibration",
    description: "Brier score, reliability curve, hit rate, attribution.",
    resource: "janus://calibration",
  },
];
