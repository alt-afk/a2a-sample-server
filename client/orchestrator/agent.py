"""The orchestrator, with two ways to use the remote helper.

1. **Call and wait**: ``AgentTool(RemoteA2aAgent(...))``. ADK's RemoteA2aAgent
   fetches the agent card, sends the message, streams the answer back; AgentTool
   makes that a function the model can call like any other. Several such calls
   in one turn run concurrently.

2. **Fire and forget**: the task tools from ``a2a_tools.py``. ``start_task``
   returns a task id at once; the model can do other things, then ``check_task``,
   ``wait_for_task``, ``send_task_message`` or ``cancel_task``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# `adk web client` imports this file without the repo root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import config  # noqa: E402

config.use_key("client")

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH, RemoteA2aAgent  # noqa: E402
from google.adk.tools.agent_tool import AgentTool  # noqa: E402

from client.a2a_tools import make_task_tools  # noqa: E402

INSTRUCTION = """You coordinate one remote helper and answer the user.

Two ways to use the helper:
- `helper(request)`: ask and wait for the answer. Use it when the answer is the next thing you need.
- `start_task(request)`: fire the same helper in the background and get a task_id at once. Use it when
  the user asks for something slow or says "in the background", or when you have more than one thing
  to ask that do not depend on each other. Then `check_task` to peek, `wait_for_task` to collect,
  `send_task_message` to follow up (the helper remembers that conversation), `cancel_task` to drop it,
  `list_tasks` to see them all.

Tell the user what you did: which tool, the task_id and state when there is one, and the answer.
Keep it short."""


def build_orchestrator(model=None, *, server_url: str = config.SERVER_URL, background_tasks: bool = True) -> LlmAgent:
    helper = RemoteA2aAgent(
        name="helper",
        agent_card=f"{server_url}{AGENT_CARD_WELL_KNOWN_PATH}",
        description="The remote helper: answers a question, or does slow research when asked. Waits for the answer.",
    )
    return LlmAgent(
        name="orchestrator",
        model=model or config.CLIENT_MODEL,
        instruction=INSTRUCTION,
        tools=[AgentTool(agent=helper), *(make_task_tools(server_url) if background_tasks else [])],
    )


root_agent = build_orchestrator()
