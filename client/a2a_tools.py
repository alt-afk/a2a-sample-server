"""The task lifecycle as ADK tools for the orchestrator.

Each tool is a thin wrapper over ``A2ATaskClient``. The only extra is
bookkeeping: every task the orchestrator starts is written to session state
under ``a2a_tasks`` so a later turn can act on a task id alone, and so the
ADK dev UI shows what is running.
"""

from __future__ import annotations

import asyncio

from google.adk.tools import ToolContext

from client.a2a_client import A2ATaskClient

STATE_KEY = "a2a_tasks"


def make_task_tools(agent_url: str) -> list:
    """start_task, check_task, wait_for_task, send_task_message, cancel_task, list_tasks."""
    clients: dict[int, A2ATaskClient] = {}  # one per event loop: httpx clients are loop-bound

    async def helper() -> A2ATaskClient:
        key = id(asyncio.get_running_loop())
        if key not in clients:
            clients[key] = A2ATaskClient(agent_url)
        return clients[key]

    def remember(tool_context: ToolContext, task: dict, request: str) -> None:
        tasks = dict(tool_context.state.get(STATE_KEY) or {})
        tasks[task["task_id"]] = {"request": request, "state": task["state"], "context_id": task["context_id"]}
        tool_context.state[STATE_KEY] = tasks

    def known(tool_context: ToolContext, task_id: str) -> dict | None:
        return (tool_context.state.get(STATE_KEY) or {}).get(task_id)

    async def start_task(request: str, tool_context: ToolContext) -> dict:
        """Start the helper on a request in the background and return at once with a task_id. Use when you can do something else meanwhile; collect the answer later with check_task or wait_for_task.

        Args:
            request: What the helper should do.
        """
        task = await (await helper()).start(request)
        remember(tool_context, task, request)
        return task

    async def check_task(task_id: str, tool_context: ToolContext) -> dict:
        """The current state of a background task; 'result' holds the answer once 'done' is true.

        Args:
            task_id: The id start_task returned.
        """
        if not known(tool_context, task_id):
            return {"error": f"unknown task_id {task_id!r}; see list_tasks"}
        task = await (await helper()).get(task_id)
        remember(tool_context, task, known(tool_context, task_id)["request"])
        return task

    async def wait_for_task(task_id: str, timeout_seconds: int, tool_context: ToolContext) -> dict:
        """Wait for a background task to finish and return its result.

        Args:
            task_id: The id start_task returned.
            timeout_seconds: How long to wait at most, e.g. 60.
        """
        if not known(tool_context, task_id):
            return {"error": f"unknown task_id {task_id!r}; see list_tasks"}
        task = await (await helper()).wait(task_id, timeout=max(1, int(timeout_seconds)))
        remember(tool_context, task, known(tool_context, task_id)["request"])
        if not task["done"]:
            task["note"] = f"still {task['state']} after {timeout_seconds}s"
        return task

    async def send_task_message(task_id: str, message: str, tool_context: ToolContext) -> dict:
        """Send a follow-up about an earlier task; the helper remembers that conversation. Returns at once with the task to collect, which may be a new task_id.

        Args:
            task_id: The task to follow up on.
            message: The follow-up.
        """
        if not known(tool_context, task_id):
            return {"error": f"unknown task_id {task_id!r}; see list_tasks"}
        task = await (await helper()).follow_up(task_id, message)
        remember(tool_context, task, message)
        return {**task, "follow_up_of": task_id}

    async def cancel_task(task_id: str, tool_context: ToolContext) -> dict:
        """Cancel a background task you no longer need.

        Args:
            task_id: The id start_task returned.
        """
        if not known(tool_context, task_id):
            return {"error": f"unknown task_id {task_id!r}; see list_tasks"}
        task = await (await helper()).cancel(task_id)
        remember(tool_context, task, known(tool_context, task_id)["request"])
        return task

    async def list_tasks(tool_context: ToolContext) -> dict:
        """Every background task started in this session, with its current state."""
        client = await helper()
        out = []
        for task_id, record in (tool_context.state.get(STATE_KEY) or {}).items():
            task = await client.get(task_id)
            out.append({"request": record["request"], **task, "result": task["result"][:200]})
        return {"tasks": out}

    return [start_task, check_task, wait_for_task, send_task_message, cancel_task, list_tasks]
