# ADR 0002: DSH shell, Python core, MCP contract

## Status

Accepted.

## Context

The project needs:

- a local-first UI and agent loop;
- a data and ML ecosystem for indicators, filings, and calibration;
- a stable interface that is not tied to a single agent client;
- reuse of the existing FlyBot / bot-social / AgentDescent / Fledge work.

Candidate bases:

- DSH for everything;
- a generic "superagent" framework;
- a Python agent framework (PydanticAI, LangGraph, CrewAI);
- a custom loop.

## Decision

- **Shell:** DSH (TypeScript) for panels, commands, cron, and approvals.
- **Core:** Python for data, memory, analysis, forecasting, and calibration.
- **Contract:** MCP for tool and resource access.
- **Storage:** SQLite in V1; Postgres + pgvector later.

## Why

- The moat is the memory schema and calibration loop, not the agent loop.
- A generic superagent would pull the project toward "chat with your portfolio".
- LangGraph/CrewAI solve orchestration, not point-in-time memory.
- MCP keeps the core usable from DSH, Claude, ChatGPT, OpenCode, or a CLI.
- DSH is a good shell because of its plugin, cron, and approval model, and
  because it is already part of the local stack.

## Consequences

- Two languages: TypeScript for the shell, Python for the core.
- The core must be usable without DSH: CLI and MCP first.
- DSH breaking changes are tolerated because the shell is replaceable.
- Every numeric result must come from the Python core, never from the LLM.
