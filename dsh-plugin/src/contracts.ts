export interface MarketDashboard {
  as_of: string;
  regime: string;
  breadth: Record<string, number>;
  volatility: Record<string, number>;
  indices: Record<string, number>;
  features_hash: string;
}

export interface SectorRow {
  sector: string;
  relative_return_63d: number;
  rs_ratio: number;
  rs_momentum: number;
  quadrant: string;
  breadth: number;
}

export interface SectorDashboard {
  as_of: string;
  benchmark: string;
  sectors: SectorRow[];
  features_hash: string;
}

export interface StockDashboard {
  as_of: string;
  entity_id: string;
  close: number;
  features: Record<string, unknown>;
  features_hash: string;
}

export interface Thesis {
  id: string;
  entity_id: string;
  persona_id?: string;
  horizon: string;
  statement: string;
  assumptions: string[];
  catalysts: string[];
  risks: string[];
  falsifiers: string[];
  status: string;
  as_of: string;
}

export interface Forecast {
  id: string;
  thesis_id: string;
  target: string;
  horizon: string;
  probability?: number;
  quantiles: Record<string, number>;
  model_version: string;
  features_hash: string;
  as_of: string;
  outcome_id?: string;
}
