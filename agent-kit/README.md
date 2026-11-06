# Agent Kit

Connects an outside agent (Claude Code, Codex, or anything that speaks MCP) to this app. The agent gets the same tools as the built-in assistant, under the account the token belongs to. Paid tools refuse to run without `confirm: true`.

## 1. Get a token

User center → MCP tokens. It is shown once. It stands for your account, so treat it like a password.

## 2. Connect

```bash
export SHORT_DRAMA_URL=https://your-host
export SHORT_DRAMA_TOKEN=your-token
python3 agent-kit/short_drama_mcp.py doctor
```

`doctor` says whether the address and the token work. Then print the setup for your client:

```bash
python3 agent-kit/short_drama_mcp.py config claude-code
```

`claude-code` and `json` connect over HTTP directly. `codex` runs `short_drama_mcp.py serve`, a stdio bridge for clients without HTTP support. It needs only Python's standard library.

## 3. Teach the agent the workflow

Copy `skills/short-drama-canvas/` into your agent's skills folder. It explains planning a workflow, confirming costs and retrying failures.
