"""A Google ADK agent that answers questions with Research.it's MCP tools.

Not part of the app: it is an outside agent, in its own environment, calling
the API's MCP endpoint the way any MCP client would.

    python -m venv .adk && .adk/bin/pip install "google-adk[mcp]"
    # for a local model instead of Gemini, also: .adk/bin/pip install litellm

    # The API, with the MCP endpoint on:
    MCP_API_KEY=some-token make dev

    RESEARCHIT_MCP_TOKEN=some-token GOOGLE_API_KEY=... \\
      .adk/bin/python examples/adk_agent.py "Which sensors does the in-car corpus use?"

    # Fully local, through LiteLLM and Ollama:
    ADK_MODEL=ollama_chat/qwen2.5:7b RESEARCHIT_MCP_TOKEN=some-token \\
      .adk/bin/python examples/adk_agent.py "..."

Checked against google-adk 2.13, with qwen2.5:7b through LiteLLM: the agent
listed the projects, searched the right one, and answered naming the paper.
"""

from __future__ import annotations

import asyncio
import os
import sys

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import types

MCP_URL = os.environ.get("RESEARCHIT_MCP_URL", "http://127.0.0.1:8000/mcp/")
MCP_TOKEN = os.environ["RESEARCHIT_MCP_TOKEN"]
MODEL = os.environ.get("ADK_MODEL", "gemini-2.5-flash")


def build_agent() -> tuple[LlmAgent, McpToolset]:
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=MCP_URL, headers={"Authorization": f"Bearer {MCP_TOKEN}"}
        ),
    )
    model: object = MODEL
    if MODEL.startswith("ollama"):
        from google.adk.models.lite_llm import LiteLlm

        model = LiteLlm(model=MODEL)

    agent = LlmAgent(
        model=model,
        name="research_analyst",
        instruction=(
            "You answer questions about research runs using the Research.it tools. "
            "Call list_projects to find the right project_id, then search_papers or "
            "ask_papers. Name the papers your answer relies on."
        ),
        tools=[toolset],
    )
    return agent, toolset


async def main(question: str) -> None:
    agent, toolset = build_agent()
    runner = InMemoryRunner(agent=agent, app_name="researchit_example")
    session = await runner.session_service.create_session(
        app_name="researchit_example", user_id="example"
    )
    try:
        async for event in runner.run_async(
            user_id="example",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=question)]),
        ):
            for part in event.content.parts if event.content else []:
                if part.function_call:
                    print(f"→ {part.function_call.name}({dict(part.function_call.args or {})})")
                elif part.text and event.is_final_response():
                    print(f"\n{part.text.strip()}")
    finally:
        await toolset.close()


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "What research runs are there?"))
