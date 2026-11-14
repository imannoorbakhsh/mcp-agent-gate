# mcp-agent-gate

A bounded, observable Python agent that uses local task and calendar MCP tools.

**Status: ~60%, work in progress**

## Architecture

```text
Claude Messages API
        |
  AgentLoop (hard steps, tokens, USD caps; JSON snapshot/resume)
        |
typed tool definitions and dispatcher
        |
ApprovalGate (writes prompt a human) -> JSONL audit log
        |
TaskCalendar MCP server -> local SQLite task/calendar mock
```

`task_calendar_mcp.server` exposes four stdio MCP tools: `list_tasks`, `list_calendar_events`, `create_task`, and `create_calendar_event`. Inputs and outputs are Pydantic models. The SQLite mock is local-only and has no credentials or external integration.

The agent loop uses the official Anthropic Python SDK and `claude-opus-5-5`. Before each API call it reserves the configured worst-case tokens and dollars, and it halts before exceeding its step, token, or dollar limit. Runs persist append-only message history and tool events in a JSON snapshot; interrupted uncertain tool calls are not replayed.

## Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Put ANTHROPIC_API_KEY in .env, then export it for your shell.
set -a; . ./.env; set +a

# Start the local MCP server over stdio.
mcp-agent-gate-mcp

# In another terminal, run a bounded agent call.
mcp-agent-gate "List my tasks and calendar events." \
  --snapshot run_snapshot.json --audit-log tool_calls.jsonl

# Resume a stopped run with its durable snapshot.
mcp-agent-gate "Continue the task." --resume \
  --snapshot run_snapshot.json --audit-log tool_calls.jsonl
```

The CLI launches the local MCP server as a stdio child process and dispatches each typed agent tool call through that MCP transport.

Write calls (`create_task`, `create_calendar_event`) prompt for terminal approval. Only `y` or `yes` proceeds. Every attempted tool call is recorded in JSON Lines at the selected audit-log path.

## Test

```bash
pytest -q
# Or, once Docker is available:
docker compose run --rm tests
```

## Safety boundaries

- No real task/calendar credentials or remote services.
- SQLite queries use DB-API placeholders.
- Timestamp inputs must include a timezone and are stored in UTC.
- `.env`, local state, logs, snapshots, and SQLite files are ignored by Git.
