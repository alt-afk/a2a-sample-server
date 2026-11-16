"""The remote agent: ``helper``.

Two tools. ``quick_fact`` answers at once. ``slow_research`` sleeps for a few
seconds first, which is what makes a background task visibly *working* from
the client side before it completes.
"""

from __future__ import annotations

import asyncio

from google.adk.agents import LlmAgent

FACTS = {
    "a2a": "A2A (Agent2Agent) is an open protocol for agents to call each other over HTTP with agent cards, tasks and messages.",
    "adk": "ADK is Google's Agent Development Kit: a Python framework for building LLM agents with tools, sub-agents and A2A support.",
    "mcp": "MCP (Model Context Protocol) standardises how a model connects to tools and data sources.",
}


def quick_fact(topic: str) -> dict:
    """A one-line fact about a topic, at once.

    Args:
        topic: What to look up, e.g. 'a2a', 'adk' or 'mcp'.
    """
    key = topic.strip().lower()
    return {"topic": topic, "fact": FACTS.get(key, f"No stored fact about {topic!r}; answer from your own knowledge.")}


async def slow_research(topic: str, seconds: int) -> dict:
    """Research a topic slowly. Takes 'seconds' to finish, so call it when the user asks for slow or deep research.

    Args:
        topic: What to research.
        seconds: How long the research takes, 1 to 30.
    """
    seconds = max(1, min(int(seconds), 30))
    await asyncio.sleep(seconds)
    return {"topic": topic, "seconds": seconds, "notes": f"After {seconds}s of research on {topic!r}: {FACTS.get(topic.strip().lower(), 'nothing stored, use what you know')}"}


def build_agent(model) -> LlmAgent:
    return LlmAgent(
        name="helper",
        model=model,
        description=(
            "A helper that answers questions. It can give a quick fact at once, or do slow "
            "research that takes several seconds when asked for slow or deep research."
        ),
        instruction=(
            "You are a helper reached over A2A. Answer briefly, in one or two sentences.\n"
            "- For a plain question, call quick_fact once and answer from it.\n"
            "- When the request says 'slow', 'slowly', 'deep' or 'research', call slow_research with the "
            "number of seconds the request names, or 8 if it names none, then answer from its notes.\n"
            "- You remember earlier messages in the same conversation; use them when asked to summarise or "
            "refer back."
        ),
        tools=[quick_fact, slow_research],
    )
