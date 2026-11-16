"""Run one prompt, or a chat, through the orchestrator and print what it does.

    python -m client.run "What is a2a?"
    python -m client.run "Research adk slowly for 10 seconds in the background, and meanwhile tell me what mcp is"
    python -m client.run            # interactive: one session, several turns, tasks survive across turns

Each tool call is printed with the time since the run started, so a start_task
that returns at once and a wait_for_task that blocks are easy to tell apart.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from google.adk.runners import InMemoryRunner
from google.genai import types


def _clip(value, n: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= n else text[:n] + " ..."


async def run_turn(runner: InMemoryRunner, session, text: str) -> str | None:
    started = time.perf_counter()
    message = types.Content(role="user", parts=[types.Part.from_text(text=text)])
    final = None
    async for event in runner.run_async(user_id=session.user_id, session_id=session.id, new_message=message):
        stamp = f"{time.perf_counter() - started:6.2f}s"
        for call in event.get_function_calls():
            print(f"[{stamp}] {event.author} -> {call.name}({_clip(call.args)})")
        for resp in event.get_function_responses():
            print(f"[{stamp}] {event.author} <- {resp.name}: {_clip(resp.response)}")
        if event.is_final_response() and event.content and event.content.parts:
            texts = [p.text for p in event.content.parts if p.text]
            if texts:
                final = "\n".join(texts)
                print(f"[{stamp}] {event.author}:\n{final}")
    return final


async def main(prompts: list[str]) -> None:
    from client.orchestrator.agent import root_agent

    runner = InMemoryRunner(agent=root_agent, app_name="simple_client")
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id="me")
    if prompts:
        for prompt in prompts:
            await run_turn(runner, session, prompt)
        return
    print("Chat with the orchestrator (empty line to quit).")
    while True:
        try:
            text = input("\nyou> ").strip()
        except EOFError:
            break
        if not text:
            break
        await run_turn(runner, session, text)
        state = (await runner.session_service.get_session(app_name=runner.app_name, user_id="me", session_id=session.id)).state
        if state.get("a2a_tasks"):
            print(f"[session a2a_tasks] {_clip(state['a2a_tasks'], 400)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
