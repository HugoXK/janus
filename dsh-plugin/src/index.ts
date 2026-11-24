export const pluginName = "janus";
export const pluginVersion = "0.1.0";

export interface JanusPluginOptions {
  /** URL of the Janus MCP server. Defaults to http://127.0.0.1:8765/mcp. */
  mcpUrl?: string;
  /** Optional local store path for the CLI-side fallback. */
  storePath?: string;
}

export const commands = [
  "janus.brief",
  "janus.market",
  "janus.sector",
  "janus.stock",
  "janus.forecast",
  "janus.thesis",
  "janus.review",
  "janus.persona",
] as const;

export type JanusCommand = (typeof commands)[number];

/**
 * The DSH plugin is a thin shell over the Janus MCP server.
 *
 * The Python core owns memory, indicators, forecasts, and calibration. The
 * plugin owns panels, commands, cron, and approvals.
 */
export function createJanusPlugin(options: JanusPluginOptions = {}) {
  return {
    name: pluginName,
    version: pluginVersion,
    options: {
      mcpUrl: options.mcpUrl ?? "http://127.0.0.1:8765/mcp",
      storePath: options.storePath,
    },
    commands,
  };
}

export default createJanusPlugin;
