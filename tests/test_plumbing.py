"""The wiring, without an API key: a scripted model stands in for Gemini.

Starts the server in a thread, then checks the agent card, the task lifecycle
through ``A2ATaskClient``, and the orchestrator using both the direct call and
the task tools. Test only; the real runs use Gemini from ``.env``.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
import pytest
import uvicorn
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("GOOGLE_API_KEY", "test-key-not-used")

from google.adk.a2a.utils.agent_to_a2a import to_a2a  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402

from client.a2a_client import A2ATaskClient  # noqa: E402
from client.orchestrator.agent import build_orchestrator  # noqa: E402
from server.agent import build_agent  # noqa: E402


class ScriptedLlm(BaseLlm):
    """Answers each request with the next script item: text, or [(tool, args)], or a callable of the request."""

    model: str = "scripted"
    script: list[Any] = []
    delay_seconds: float = 0.0
    requests: list[LlmRequest] = []

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["scripted.*"]

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        item = self.script[min(len(self.requests) - 1, len(self.script) - 1)]
        if callable(item):
            item = item(llm_request)
        parts = [types.Part.from_text(text=item)] if isinstance(item, str) else [
            types.Part.from_function_call(name=n, args=a) for n, a in item
        ]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def last_response(llm_request: LlmRequest, tool: str) -> Any:
    for content in reversed(llm_request.contents or []):
        for part in reversed(content.parts or []):
            if part.function_response and part.function_response.name == tool:
                return part.function_response.response
    return None


@pytest.fixture(scope="module")
def server():
    # The helper's model: 1.5 s per answer, so a task is visibly 'working'.
    llm = ScriptedLlm(delay_seconds=1.5, script=["helper says hi"])
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = to_a2a(build_agent(llm), host="127.0.0.1", port=port)
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=uv.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/.well-known/agent-card.json", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield {"url": url, "llm": llm}
    uv.should_exit = True


def test_card(server):
    card = httpx.get(f"{server['url']}/.well-known/agent-card.json").json()
    assert card["name"] == "helper"
    assert {s["name"] for s in card["skills"]} >= {"quick_fact", "slow_research"}


def test_task_lifecycle_direct(server):
    async def go():
        async with A2ATaskClient(server["url"]) as helper:
            t0 = time.perf_counter()
            task = await helper.start("hello")
            assert time.perf_counter() - t0 < 1.0, "start waited for the helper"
            assert not task["done"] and task["state"] in ("submitted", "working")

            peek = await helper.get(task["task_id"])
            assert not peek["done"]

            done = await helper.wait(task["task_id"], timeout=10)
            assert done["done"] and done["state"] == "completed" and "helper says hi" in done["result"]

            before = len(server["llm"].requests)
            follow = await helper.follow_up(task["task_id"], "and again")
            assert follow["context_id"] == task["context_id"] and follow["task_id"] != task["task_id"]
            follow = await helper.wait(follow["task_id"], timeout=10)
            assert follow["done"]
            # same session on the server: the model saw the earlier exchange
            assert len(server["llm"].requests[before].contents) > len(server["llm"].requests[before - 1].contents)

            task = await helper.start("slow one")
            cancelled = await helper.cancel(task["task_id"])
            assert cancelled["state"] == "canceled"

    asyncio.run(go())


def test_orchestrator_direct_call_and_background_task(server):
    llm = ScriptedLlm(
        script=[
            [("start_task", {"request": "research slowly"})],
            # peek at the task and make a direct call in the same turn; both run while the task is working
            lambda req: [
                ("check_task", {"task_id": last_response(req, "start_task")["task_id"]}),
                ("helper", {"request": "what is a2a"}),
            ],
            lambda req: [("wait_for_task", {"task_id": last_response(req, "start_task")["task_id"], "timeout_seconds": 10})],
            [("list_tasks", {})],
            "DONE",
        ]
    )
    orchestrator = build_orchestrator(model=llm, server_url=server["url"])

    async def go():
        runner = InMemoryRunner(agent=orchestrator, app_name="t")
        session = await runner.session_service.create_session(app_name="t", user_id="u")
        msg = types.Content(role="user", parts=[types.Part.from_text(text="go")])
        final = None
        async for event in runner.run_async(user_id="u", session_id=session.id, new_message=msg):
            if event.is_final_response() and event.content and event.content.parts and event.content.parts[0].text:
                final = event.content.parts[0].text
        return final, (await runner.session_service.get_session(app_name="t", user_id="u", session_id=session.id)).state

    final, state = asyncio.run(go())
    assert final == "DONE"
    last = llm.requests[-1]
    assert "helper says hi" in str(last_response(last, "helper"))
    assert not last_response(last, "check_task")["done"]
    waited = last_response(last, "wait_for_task")
    assert waited["done"] and "helper says hi" in waited["result"]
    assert len(last_response(last, "list_tasks")["tasks"]) == 1
    assert len(state["a2a_tasks"]) == 1
