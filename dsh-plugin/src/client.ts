import type { Forecast, Thesis } from "./contracts.js";

export type ToolCaller = (
  name: string,
  args: Record<string, unknown>,
) => Promise<unknown>;

export class JanusClient {
  constructor(private readonly callTool: ToolCaller) {}

  asOfQuery(
    entityId: string,
    asOf: string,
    options: {
      mode?: "published" | "observed";
      kind?: string;
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<unknown> {
    return this.callTool("janus_as_of_query", {
      entity_id: entityId,
      as_of: asOf,
      ...options,
    });
  }

  createThesis(input: {
    entity_id: string;
    statement: string;
    horizon: string;
    as_of: string;
    persona_id?: string;
    falsifiers?: string[];
  }): Promise<Thesis> {
    return this.callTool("janus_thesis_create", input) as Promise<Thesis>;
  }

  listTheses(): Promise<Thesis[]> {
    return this.callTool("janus_thesis_list", {}) as Promise<Thesis[]>;
  }

  createForecast(input: {
    thesis_id: string;
    target: string;
    horizon: string;
    as_of: string;
    probability: number;
    model_version: string;
    features_hash: string;
  }): Promise<Forecast> {
    return this.callTool("janus_forecast_create", input) as Promise<Forecast>;
  }

  listForecasts(thesisId?: string): Promise<Forecast[]> {
    return this.callTool("janus_forecast_list", {
      thesis_id: thesisId,
    }) as Promise<Forecast[]>;
  }

  settleForecast(input: {
    prediction_id: string;
    start_price: number;
    end_price: number;
    realized_at: string;
    source?: string;
  }): Promise<unknown> {
    return this.callTool("janus_forecast_settle", input);
  }

  debrief(input: {
    prediction_id: string;
    features: Record<string, number>;
    regime?: string;
    calibration?: number;
    lessons?: string;
  }): Promise<unknown> {
    return this.callTool("janus_review_debrief", input);
  }

  calibrate(): Promise<unknown> {
    return this.callTool("janus_calibrate", {});
  }

  listPersonas(): Promise<unknown> {
    return this.callTool("janus_persona_list", {});
  }

  runBeliefBench(
    scenariosPath: string,
    baseline: "always_up" | "always_down" | "random" = "always_up",
  ): Promise<unknown> {
    return this.callTool("janus_beliefbench_run", {
      scenarios_path: scenariosPath,
      baseline,
    });
  }
}
