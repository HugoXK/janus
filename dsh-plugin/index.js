import { defineTool } from '@deepseek-ai/dsh-tools'
import { createDailyCron } from './cron.js'

export const name = 'janus'
export const inject = ['tools']

const DEFAULT_BASE_URL = 'http://127.0.0.1:8766'
const DEFAULT_DAILY_AT = '09:00'
const TOOL_TIMEOUT_MS = 15000

function timeoutSignal() {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    return AbortSignal.timeout(TOOL_TIMEOUT_MS)
  }
  return undefined
}

async function getJson(baseUrl, path, token) {
  const response = await fetch(`${baseUrl}${path}`, {
    signal: timeoutSignal(),
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`Janus API ${response.status}: ${text.slice(0, 200)}`)
  }
  return await response.json()
}

function normalizeWatchlist(value) {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item).trim()).filter(Boolean)
}

function resolveCronConfig(config) {
  const daily = config.dailyBrief && typeof config.dailyBrief === 'object'
    ? config.dailyBrief
    : {}
  const enabled = daily.enabled ?? config.daily !== false
  const at = String(daily.at || config.dailyAt || DEFAULT_DAILY_AT)
  const timeZone = String(
    daily.timeZone ||
      config.timezone ||
      Intl.DateTimeFormat().resolvedOptions().timeZone ||
      'UTC',
  )
  return { enabled, at, timeZone }
}

export function apply(ctx, config = {}) {
  const baseUrl = String(config.baseUrl || DEFAULT_BASE_URL)
  const token = config.token ? String(config.token) : undefined
  const watchlist = normalizeWatchlist(config.watchlist)
  const defaultEntity = watchlist.length > 0 ? watchlist[0] : ''
  let lastBrief = null
  let lastBriefAt = null
  let lastError = null

  const refresh = async () => {
    try {
      lastBrief = await getJson(
        baseUrl,
        `/api/brief?entity_id=${encodeURIComponent(defaultEntity)}`,
        token,
      )
      lastBriefAt = new Date().toISOString()
      lastError = null
      return lastBrief
    } catch (error) {
      lastError = String(error?.message ?? error)
      return null
    }
  }

  const disposers = []
  const register = (tool) => {
    const { path, ...definition } = tool
    disposers.push(
      ctx.tools.register(
        defineTool({
          output: { schema: {} },
          presentCall: () => ({ card: 'generic', title: tool.name, kind: 'read' }),
          timeoutMs: TOOL_TIMEOUT_MS,
          ...definition,
          execute:
            definition.execute ??
            (async (args) => await getJson(baseUrl, path(args ?? {}), token)),
        }),
      ),
    )
  }

  register({
    name: 'janus_brief',
    description:
      'Daily Janus brief for an entity: calibration, theses, forecasts, and recent evidence.',
    parameters: {
      entity_id: { type: 'string', required: true },
      as_of: { type: 'string' },
    },
    path: (args) =>
      `/api/brief?entity_id=${encodeURIComponent(args.entity_id)}${
        args.as_of ? `&as_of=${encodeURIComponent(args.as_of)}` : ''
      }`,
  })

  register({
    name: 'janus_market',
    description: 'Market panel: regime, breadth, volatility, and indices.',
    parameters: {},
    path: () => '/api/panels/market',
  })

  register({
    name: 'janus_sector',
    description: 'Sector panel: relative rotation, momentum, breadth, and quadrant.',
    parameters: {},
    path: () => '/api/panels/sector',
  })

  register({
    name: 'janus_stock',
    description: 'Stock panel from the latest point-in-time feature materialization.',
    parameters: {
      entity_id: { type: 'string', required: true },
      as_of: { type: 'string' },
    },
    path: (args) =>
      `/api/panels/stock?entity_id=${encodeURIComponent(args.entity_id)}${
        args.as_of ? `&as_of=${encodeURIComponent(args.as_of)}` : ''
      }`,
  })

  register({
    name: 'janus_observations',
    description: 'Recent as-of observations for one entity.',
    parameters: {
      entity_id: { type: 'string', required: true },
      as_of: { type: 'string' },
      limit: { type: 'integer' },
    },
    path: (args) =>
      `/api/as_of?entity_id=${encodeURIComponent(args.entity_id)}${
        args.as_of ? `&as_of=${encodeURIComponent(args.as_of)}` : ''
      }${args.limit ? `&limit=${encodeURIComponent(args.limit)}` : ''}`,
  })

  register({
    name: 'janus_theses',
    description: 'List theses and their falsifiers.',
    parameters: {},
    path: () => '/api/theses',
  })

  register({
    name: 'janus_forecasts',
    description: 'List forecasts, optionally for one thesis.',
    parameters: { thesis_id: { type: 'string' } },
    path: (args) =>
      `/api/forecasts${
        args.thesis_id ? `?thesis_id=${encodeURIComponent(args.thesis_id)}` : ''
      }`,
  })

  register({
    name: 'janus_calibrate',
    description: 'Calibration report over settled predictions.',
    parameters: {},
    path: () => '/api/calibrate',
  })

  register({
    name: 'janus_daily',
    description: 'Return the latest cached daily brief, refreshing it if needed.',
    parameters: {},
    path: () => '/api/brief',
    execute: async () => {
      if (lastBrief === null) await refresh()
      return lastBrief ?? { error: lastError ?? 'brief unavailable' }
    },
  })

  const commandHandler = async (invocation) => {
    const [subcommand = 'brief', ...rest] = String(invocation?.rawInput ?? '')
      .trim()
      .split(/\s+/)
      .filter(Boolean)
    try {
      switch (subcommand) {
        case 'brief':
          return { kind: 'success', text: JSON.stringify(await refresh(), null, 2) }
        case 'market':
          return {
            kind: 'success',
            text: JSON.stringify(await getJson(baseUrl, '/api/panels/market', token), null, 2),
          }
        case 'sector':
          return {
            kind: 'success',
            text: JSON.stringify(await getJson(baseUrl, '/api/panels/sector', token), null, 2),
          }
        case 'stock': {
          const entity = encodeURIComponent(rest[0] || defaultEntity)
          if (!entity) {
            return { kind: 'error', text: 'Usage: /janus stock <ENTITY> [as_of]' }
          }
          const asOf = rest[1] ? `&as_of=${encodeURIComponent(rest[1])}` : ''
          return {
            kind: 'success',
            text: JSON.stringify(
              await getJson(baseUrl, `/api/panels/stock?entity_id=${entity}${asOf}`, token),
              null,
              2,
            ),
          }
        }
        case 'forecast':
          return {
            kind: 'success',
            text: JSON.stringify(await getJson(baseUrl, '/api/forecasts', token), null, 2),
          }
        case 'thesis':
          return {
            kind: 'success',
            text: JSON.stringify(await getJson(baseUrl, '/api/theses', token), null, 2),
          }
        case 'review':
        case 'calibrate':
          return {
            kind: 'success',
            text: JSON.stringify(await getJson(baseUrl, '/api/calibrate', token), null, 2),
          }
        default:
          return {
            kind: 'error',
            text:
              'Usage: /janus [brief|market|sector|stock|forecast|thesis|review|calibrate]',
          }
      }
    } catch (error) {
      return { kind: 'error', text: String(error?.message ?? error) }
    }
  }

  const commands = ctx.get('commands')
  if (commands !== undefined) {
    commands.register({
      name: 'janus',
      description: 'Show the Janus brief, panels, theses, forecasts, and calibration',
      input: { hint: '[brief|market|sector|stock|forecast|thesis|review|calibrate]' },
      handler: commandHandler,
    })
  }

  const cronConfig = resolveCronConfig(config)
  let cron = null
  try {
    cron = createDailyCron({
      at: cronConfig.at,
      timeZone: cronConfig.timeZone,
      run: refresh,
      onError: (error) => {
        lastError = String(error?.message ?? error)
      },
    })
    if (cronConfig.enabled) cron.start()
  } catch (error) {
    lastError = String(error?.message ?? error)
  }

  const cleanup = () => {
    cron?.stop()
    for (const dispose of disposers.splice(0)) dispose?.()
  }
  if (typeof ctx.effect === 'function') {
    ctx.effect(() => cleanup, 'janus:lifetime')
  } else {
    ctx.on?.('dispose', cleanup)
  }

  void refresh()

  return {
    baseUrl,
    watchlist,
    refresh,
    get lastBrief() {
      return lastBrief
    },
    get lastBriefAt() {
      return lastBriefAt
    },
    get lastError() {
      return lastError
    },
    get dailyBrief() {
      return {
        enabled: cronConfig.enabled,
        at: cronConfig.at,
        timeZone: cronConfig.timeZone,
        nextRunAt: cron?.nextRunAt ?? null,
      }
    },
  }
}
