# simple: one orchestrator, one remote A2A agent

The smallest setup that shows every way the client can use a remote agent
over A2A with Google ADK. Gemini through Google AI Studio keys only.

```
client/orchestrator   the orchestrator (ADK LlmAgent) and its tools
client/a2a_client.py  the A2A task lifecycle in plain Python
client/a2a_tools.py   the same lifecycle as ADK tools
server/agent.py       the remote agent: "helper", a quick fact or slow research
server/app.py         serves it over A2A with to_a2a
demo_tasks.py         walks the lifecycle one call at a time, no orchestrator LLM
docs/                 what was added on top of ADK, and why
tests/                plumbing test with a scripted model (test only)
```

[docs/A2A-CLIENT-NOTES.md](docs/A2A-CLIENT-NOTES.md) explains what ADK gives
out of the box, what it leaves unused, and what this repo adds.

## Setup

```powershell
cd simple
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Paste your AI Studio key into `.env` as `GOOGLE_API_KEY`. A second key as
`SERVER_GOOGLE_API_KEY` lets the server spend a separate per-minute quota.
`CLIENT_MODEL` and `SERVER_MODEL` default to `gemini-3.5-flash-lite`;
`python list_models.py` prints what your key can call; lite models have higher free-tier rates if you hit 429s.

## Run

Terminal 1, the remote agent:

```powershell
.\.venv\Scripts\python -m server.app
```

Card: `http://localhost:8002/.well-known/agent-card.json`.

Terminal 2, pick one:

```powershell
# The protocol, step by step, without an orchestrator model:
# call-and-wait, fire-and-forget with polling, follow-up, cancel.
.\.venv\Scripts\python demo_tasks.py

# The orchestrator deciding for itself.
.\.venv\Scripts\python -m client.run "What is a2a?"
.\.venv\Scripts\python -m client.run "Research adk slowly for 10 seconds in the background, and meanwhile tell me what mcp is"
.\.venv\Scripts\python -m client.run "Ask the helper about a2a and about mcp at the same time"

# A chat: tasks started in one turn can be checked or followed up in the next.
.\.venv\Scripts\python -m client.run

# The ADK dev UI; session state shows a2a_tasks.
.\.venv\Scripts\adk web client
```

Every tool call is printed with the time since the turn started. A
`start_task` returns in well under a second while the helper is still
working; a `wait_for_task` blocks until it is done.

## What to look at

- `helper(...)` in the printout is `AgentTool(RemoteA2aAgent)`: ADK's own
  call-and-wait path. Two of them in one turn run concurrently.
- `start_task`, `check_task`, `wait_for_task`, `send_task_message`,
  `cancel_task`, `list_tasks` are the task lifecycle: `message/send` with
  `return_immediately`, `tasks/get`, `tasks/cancel`.
- A follow-up keeps the conversation: the server maps the A2A context id to
  the helper's session, so "summarise what you just said" works.

## Test without a key

```powershell
.\.venv\Scripts\python -m pytest -q
```

Starts the server in a thread with a scripted model and checks the card, the
lifecycle through `A2ATaskClient`, and the orchestrator using both paths.
