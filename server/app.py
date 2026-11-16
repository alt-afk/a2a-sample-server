"""Serve the helper over A2A.

    python -m server.app
    # or
    uvicorn server.app:a2a_app --host localhost --port 8002

``to_a2a`` wraps the agent in a Starlette app: the agent card at
``/.well-known/agent-card.json`` and the JSON-RPC endpoint at ``/``. Its
executor runs the agent, emits task states (submitted, working, completed,
canceled), stores tasks in memory for ``tasks/get``, and maps the A2A context
id to the agent's session so follow-ups keep history.
"""

from __future__ import annotations

import config

config.use_key("server")

from google.adk.a2a.utils.agent_to_a2a import to_a2a  # noqa: E402

from server.agent import build_agent  # noqa: E402

a2a_app = to_a2a(build_agent(config.SERVER_MODEL), host=config.SERVER_HOST, port=config.SERVER_PORT)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(a2a_app, host=config.SERVER_HOST, port=config.SERVER_PORT)
