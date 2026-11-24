import type { JanusCommand } from "./index.js";

export const commandHelp: Record<JanusCommand, string> = {
  "janus.brief": "Show today's market brief and thesis changes.",
  "janus.market": "Open the market dashboard: breadth, volatility, regime.",
  "janus.sector": "Open a sector dashboard: relative strength, flows, revisions.",
  "janus.stock": "Open a stock dashboard: trend, momentum, fundamentals, events.",
  "janus.forecast": "Create or list a probabilistic forecast.",
  "janus.thesis": "Create, update, or list an explicit thesis.",
  "janus.review": "Debrief a prediction: attribution and calibration.",
  "janus.persona": "Switch or compare an investment taste profile.",
};

export const commandTools: Record<JanusCommand, string> = {
  "janus.brief": "janus_calibrate",
  "janus.market": "janus_as_of_query",
  "janus.sector": "janus_as_of_query",
  "janus.stock": "janus_as_of_query",
  "janus.forecast": "janus_forecast_create",
  "janus.thesis": "janus_thesis_create",
  "janus.review": "janus_review_debrief",
  "janus.persona": "janus_persona_list",
};
