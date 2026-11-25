---
name: janus
description: Point-in-time market memory, probabilistic forecasts, calibration, and belief review.
---

# Janus

Janus is a local-first market research agent. This skill pack connects DSH to the
Janus JSON API and exposes panels, commands, tools, and a daily brief.

## Start the API

```bash
uv run janus serve --host 127.0.0.1 --port 8766
```

The API reads the same SQLite store as the CLI. Set `JANUS_DB` or pass `--db` to
use another store.

## Tools

| Tool | Purpose |
| --- | --- |
| `janus_brief` | Daily brief: calibration, theses, forecasts, recent evidence |
| `janus_market` | Market panel: regime, indices, breadth, volatility |
| `janus_sector` | Sector panel: rotation, momentum, breadth, quadrant |
| `janus_stock` | Stock panel from the latest feature materialization |
| `janus_observations` | Recent as-of observations for one entity |
| `janus_theses` | Theses and falsifiers |
| `janus_forecasts` | Forecast ledger, optionally for one thesis |
| `janus_calibrate` | Brier, ECE, and slices over settled predictions |
| `janus_daily` | Latest cached daily brief |

## Commands

`/janus` accepts one subcommand:

```
/janus brief
/janus market
/janus sector
/janus stock AAPL [as_of]
/janus forecast
/janus thesis
/janus review
/janus calibrate
```

## Panels

The browser half registers a Janus dock in `conversation.input.dock`. It shows
the latest Brier score and entity, and expands into Market, Sector, Stock,
Thesis, and Calibration tabs. Each panel is a thin client over the JSON API; it
does not duplicate the Python core.

Panels load loading, empty, error, and explicit `not_materialized` states. Use
`/api/panels/<panel>?fixture=1` for contract-shaped fixture data while building
the UI. Market and sector dashboards return `not_materialized` until their
features are built; the stock panel reads materialized features at or before the
requested `as_of`.

Panel API:

| Route | Payload |
| --- | --- |
| `GET /api/panels` | Available panels and their hints |
| `GET /api/panels/market` | MarketDashboard or `not_materialized` |
| `GET /api/panels/sector` | SectorDashboard or `not_materialized` |
| `GET /api/panels/stock?entity_id=...&as_of=...` | StockDashboard or `not_materialized` |
| `GET /api/brief?entity_id=...` | Brief used by the tabs |

## Configuration

```yaml
- insert:
    - id: janus
      name: '@hugoxk/janus-dsh'
      config:
        baseUrl: http://127.0.0.1:8766
        watchlist: [AAPL, NVDA]
        dailyBrief:
          at: '09:00'
          timeZone: Asia/Shanghai
          enabled: true
```

`dailyBrief.at` is local `HH:MM` in `dailyBrief.timeZone`. The brief refreshes
once per day at that time and is cached for `janus_daily`; the panel also
refreshes every five minutes while mounted.

The browser defaults to `http://127.0.0.1:8766` and the host watchlist. Override
it before the DSH web app loads with `window.__JANUS_DSH_CONFIG__ = { baseUrl,
watchlist }`, or persist `{ "baseUrl": "...", "watchlist": [...] }` under the
`janus.dsh.config` localStorage key.

## Rules

- Janus is research tooling, not investment advice.
- It does not execute trades.
- Every claim should cite a source and an as-of time.
- Sector and stock panels are read-only consumers of the JSON API.
