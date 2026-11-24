export interface Panel {
  id: string;
  title: string;
  description: string;
}

export const panels: Panel[] = [
  {
    id: "market",
    title: "Market",
    description: "Indices, breadth, volatility, liquidity, macro, regime.",
  },
  {
    id: "sector",
    title: "Sector",
    description: "Relative rotation, momentum, breadth, revisions, flows.",
  },
  {
    id: "stock",
    title: "Stock",
    description: "Trend, momentum, volatility, volume, fundamentals, events.",
  },
  {
    id: "thesis",
    title: "Thesis",
    description: "Beliefs, assumptions, catalysts, risks, falsifiers.",
  },
  {
    id: "calibration",
    title: "Calibration",
    description: "Brier score, reliability curve, hit rate, attribution.",
  },
];
