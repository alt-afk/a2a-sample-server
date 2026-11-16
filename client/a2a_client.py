"""The A2A task lifecycle, as plain Python on top of the a2a-sdk client.

No ADK here. ``demo_tasks.py`` uses this directly so every protocol call can
be watched one at a time; ``a2a_tools.py`` wraps the same methods as tools
for the orchestrator.

    async with A2ATaskClient("http://localhost:8002") as helper:
        task = await helper.start("Research a2a slowly, 10 seconds")   # returns at once
        task = await helper.get(task["task_id"])                        # submitted / working
        task = await helper.wait(task["task_id"], timeout=30)           # completed, with result
        more = await helper.follow_up(task["task_id"], "Summarise that in five words")
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
from a2a import types as a2a
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.utils.errors import TaskNotCancelableError

TERMINAL = {
    a2a.TaskState.TASK_STATE_COMPLETED,
    a2a.TaskState.TASK_STATE_FAILED,
    a2a.TaskState.TASK_STATE_CANCELED,
    a2a.TaskState.TASK_STATE_REJECTED,
}


def state_name(state: int) -> str:
    return a2a.TaskState.Name(state).removeprefix("TASK_STATE_").lower()


def _text(parts) -> str:
    return "\n".join(p.text for p in parts if p.HasField("text") and p.text)


def summary(task: a2a.Task) -> dict[str, Any]:
    """A task as plain JSON: id, context, state, and the agent's answer once done."""
    return {
        "task_id": task.id,
        "context_id": task.context_id,
        "state": state_name(task.status.state),
        "done": task.status.state in TERMINAL,
        "status_message": _text(task.status.message.parts) if task.status.HasField("message") else "",
        "result": "\n".join(t for t in (_text(a.parts) for a in task.artifacts) if t),
    }


class A2ATaskClient:
    """One remote agent, by its base URL (the card is at /.well-known/agent-card.json)."""

    def __init__(self, agent_url: str, timeout: float = 60.0):
        self.agent_url = agent_url.rstrip("/")
        self.timeout = timeout
        self.card: a2a.AgentCard | None = None
        self._http: httpx.AsyncClient | None = None
        self._client: Client | None = None

    async def connect(self) -> a2a.AgentCard:
        if self._client is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
            self.card = await A2ACardResolver(self._http, base_url=self.agent_url).get_agent_card()
            # streaming=False: plain message/send. polling=True: every send asks
            # the server to return immediately with the task instead of waiting.
            config = ClientConfig(streaming=False, polling=True, httpx_client=self._http)
            self._client = ClientFactory(config).create(self.card)
        return self.card

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        self._client = None
        self._http = None

    async def __aenter__(self) -> "A2ATaskClient":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # --- the protocol calls ------------------------------------------------

    async def start(self, request: str, *, context_id: str | None = None, task_id: str | None = None) -> dict:
        """message/send with return_immediately: back at once with the new task."""
        client = await self._ready()
        message = a2a.Message(message_id=uuid.uuid4().hex, role=a2a.Role.ROLE_USER, parts=[a2a.Part(text=request)])
        if context_id:
            message.context_id = context_id
        if task_id:
            message.task_id = task_id
        send = a2a.SendMessageRequest(message=message)
        send.configuration.return_immediately = True
        async for event in client.send_message(send):
            if event.HasField("task"):
                return summary(event.task)
            if event.HasField("message"):  # a stateless reply with no task
                reply = event.message
                return {"task_id": "", "context_id": reply.context_id, "state": "completed", "done": True,
                        "status_message": "", "result": _text(reply.parts)}
        raise RuntimeError("message/send returned nothing")

    async def get(self, task_id: str) -> dict:
        """tasks/get: the task as the server has it now."""
        client = await self._ready()
        return summary(await client.get_task(a2a.GetTaskRequest(id=task_id)))

    async def wait(self, task_id: str, timeout: float = 60.0, poll: float = 0.5) -> dict:
        """tasks/get in a loop until the task is terminal or the timeout passes."""
        deadline = time.monotonic() + timeout
        while True:
            task = await self.get(task_id)
            if task["done"] or time.monotonic() >= deadline:
                return task
            await asyncio.sleep(poll)

    async def follow_up(self, task_id: str, message: str) -> dict:
        """Continue the conversation behind a task.

        While the task is open (working, input-required) the message names the
        task. Once it is terminal the server refuses messages for it, so the
        message names only the context: a new task in the same conversation,
        and the agent still has the history.
        """
        current = await self.get(task_id)
        return await self.start(
            message,
            context_id=current["context_id"],
            task_id=None if current["done"] else task_id,
        )

    async def cancel(self, task_id: str) -> dict:
        """tasks/cancel. A task that already finished cannot be cancelled; its current state comes back with a note."""
        client = await self._ready()
        try:
            return summary(await client.cancel_task(a2a.CancelTaskRequest(id=task_id)))
        except TaskNotCancelableError:
            task = await self.get(task_id)
            task["note"] = f"not cancelable: already {task['state']}"
            return task

    async def call(self, request: str, timeout: float = 60.0) -> str:
        """Start and wait: the blocking call, for comparison."""
        task = await self.start(request)
        if not task["done"]:
            task = await self.wait(task["task_id"], timeout=timeout)
        return task["result"] or task["status_message"]

    async def _ready(self) -> Client:
        await self.connect()
        assert self._client is not None
        return self._client
