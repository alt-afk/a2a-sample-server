"""Walk through the A2A task lifecycle against the running server, one call at a time.

    python demo_tasks.py

No orchestrator model is involved: this is the client side of the protocol in
plain Python (client/a2a_client.py), so the output shows exactly what each A2A
call returns. The server still needs its Gemini key, since the helper is a
real agent.
"""

from __future__ import annotations

import asyncio
import json
import time

import config
from client.a2a_client import A2ATaskClient

T0 = time.perf_counter()


def show(label: str, value) -> None:
    print(f"[{time.perf_counter() - T0:6.2f}s] {label}")
    print("         " + json.dumps(value, ensure_ascii=False)[:400])


async def main() -> None:
    async with A2ATaskClient(config.SERVER_URL) as helper:
        card = helper.card
        show("agent card", {"name": card.name, "description": card.description, "skills": [s.name for s in card.skills]})

        print("\n--- 1. call and wait (start + wait) ---")
        show("answer", await helper.call("What is a2a?"))

        print("\n--- 2. fire and forget ---")
        task = await helper.start("Research adk slowly, take 8 seconds.")
        show("start -> returns at once", task)
        while not task["done"]:
            await asyncio.sleep(1.5)
            task = await helper.get(task["task_id"])
            show("get  -> polling", {k: task[k] for k in ("task_id", "state", "done")})
        show("completed, result", task["result"])

        print("\n--- 3. follow-up in the same conversation ---")
        follow = await helper.follow_up(task["task_id"], "Summarise what you just told me in five words.")
        show("follow_up -> new task, same context_id", {**follow, "same_context": follow["context_id"] == task["context_id"]})
        follow = await helper.wait(follow["task_id"], timeout=60)
        show("waited, result", follow["result"])

        print("\n--- 4. cancel ---")
        task = await helper.start("Research mcp slowly, take 20 seconds.")
        show("start", {k: task[k] for k in ("task_id", "state")})
        await asyncio.sleep(1.0)
        show("cancel", await helper.cancel(task["task_id"]))
        show("get after cancel", await helper.get(task["task_id"]))


if __name__ == "__main__":
    asyncio.run(main())
