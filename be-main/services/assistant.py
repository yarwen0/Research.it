"""Conversations with the research assistant.

A turn runs on the job runner exactly like a research run: it outlives a
dropped connection, its events can be resumed from any sequence number, and
its LLM calls are recorded per stage (GET /api/jobs/{id}/metrics). The
conversation itself — what was asked and answered, and what each answer
cited — lives in agent_threads and agent_messages.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from agents.graph import RECURSION_LIMIT, AssistantDeps, build_graph
from agents.tools import EvidenceLog, ProjectTools
from core import create_llm_client
from db.models import AgentMessage, AgentThread
from db.session import session_scope
from retrieval.embedder import ClientEmbedder, Embedder
from services.events import PipelineEvent, completed, error, processing, progress

logger = logging.getLogger(__name__)

# How much of a conversation goes back to the model with each new question:
# enough for "what about its limitations?" to resolve, bounded so a long
# thread does not crowd the evidence out of a local model's context.
HISTORY_MESSAGES = 6
HISTORY_CHARS = 4000
_TITLE_CHARS = 80


class ThreadNotFoundError(LookupError):
    """No such thread in this project."""


def create_thread(project_id: str, opening_message: str) -> str:
    thread_id = uuid.uuid4().hex
    title = " ".join(opening_message.split())
    with session_scope() as session:
        session.add(
            AgentThread(
                id=thread_id,
                project_id=project_id,
                title=title if len(title) <= _TITLE_CHARS else title[: _TITLE_CHARS - 1] + "…",
            )
        )
    return thread_id


def require_thread(thread_id: str, project_id: str) -> None:
    with session_scope() as session:
        thread = session.get(AgentThread, thread_id)
        if thread is None or thread.project_id != project_id:
            raise ThreadNotFoundError(thread_id)


def history_for(thread_id: str) -> str:
    """The latest messages of a thread, oldest first, within the budget."""
    with session_scope() as session:
        rows = session.scalars(
            select(AgentMessage)
            .where(AgentMessage.thread_id == thread_id)
            .order_by(AgentMessage.id.desc())
            .limit(HISTORY_MESSAGES)
        ).all()
        turns = [(row.role, " ".join(row.content.split())) for row in reversed(rows)]

    lines: list[str] = []
    budget = HISTORY_CHARS
    # Newest first, so it is the oldest that gets cut.
    for role, text in reversed(turns):
        line = f"{'User' if role == 'user' else 'Assistant'}: {text}"
        if len(line) > budget:
            break
        lines.insert(0, line)
        budget -= len(line)
    return "\n".join(lines)


def _record(thread_id: str, role: str, content: str, *, payload=None, job_id=None) -> None:
    with session_scope() as session:
        session.add(
            AgentMessage(
                thread_id=thread_id, role=role, content=content, payload=payload, job_id=job_id
            )
        )
        thread = session.get(AgentThread, thread_id)
        if thread is not None:
            thread.updated_at = datetime.now(timezone.utc)


def list_threads(project_id: str) -> list[dict[str, Any]]:
    with session_scope() as session:
        count = func.count(AgentMessage.id).label("messages")
        rows = session.execute(
            select(AgentThread, count)
            .outerjoin(AgentMessage, AgentMessage.thread_id == AgentThread.id)
            .where(AgentThread.project_id == project_id)
            .group_by(AgentThread.id)
            .order_by(AgentThread.updated_at.desc())
        ).all()
        return [
            {
                "thread_id": thread.id,
                "title": thread.title,
                "messages": messages,
                "created_at": thread.created_at.isoformat(),
                "updated_at": thread.updated_at.isoformat(),
            }
            for thread, messages in rows
        ]


def get_thread(thread_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        thread = session.get(AgentThread, thread_id)
        if thread is None:
            return None
        return {
            "thread_id": thread.id,
            "project_id": thread.project_id,
            "title": thread.title,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "payload": message.payload,
                    "job_id": message.job_id,
                    "created_at": message.created_at.isoformat(),
                }
                for message in thread.messages
            ],
        }


def describe(event: dict[str, Any]) -> str:
    """A progress line for one event from inside the graph."""
    kind = event.get("type")
    if kind == "plan":
        return f"Delegating to {', '.join(event['specialists'])}"
    if kind == "tool_call":
        arguments = ", ".join(f"{name}={value!r}" for name, value in event["arguments"].items())
        return f"{event['specialist']} → {event['tool']}({arguments})"
    if kind == "observation":
        found = len(event["evidence"])
        return f"{event['specialist']} ← {event['tool']}: {found} piece{'s' if found != 1 else ''} of evidence"
    if kind == "self_check":
        return f"{event['specialist']}: {event['problem']}; asked again"
    if kind == "finding":
        return f"{event['specialist']} finished"
    if kind == "draft":
        label = "Drafted an answer" if event["revision"] == 0 else "Revised the answer"
        return f"{label} citing {', '.join(event['cited']) or 'nothing'}"
    if kind == "critique":
        if event["verdict"] == "accept":
            return "The critic accepted the answer"
        return f"The critic asked for a revision: {'; '.join(event['problems'])}"
    return str(kind)


class AssistantTurn:
    """One question to the assistant, runnable by the job runner."""

    def __init__(
        self,
        *,
        project_id: str,
        thread_id: str,
        message: str,
        llm_client: Any = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.project_id = project_id
        self.thread_id = thread_id
        self.message = message
        self._llm = llm_client
        self._embedder = embedder
        # Set by the caller once the job exists, so each message can point at
        # the job that recorded its turn.
        self.job_id: str | None = None

    async def run(self) -> AsyncGenerator[PipelineEvent, None]:
        try:
            llm = self._llm or create_llm_client()
            embedder = self._embedder or ClientEmbedder(llm)
            evidence = EvidenceLog()
            graph = build_graph(
                AssistantDeps(llm, ProjectTools(self.project_id, embedder, evidence), evidence)
            )

            # Read before this turn's question is added to it.
            history = history_for(self.thread_id)
            _record(self.thread_id, "user", self.message, job_id=self.job_id)
            yield processing("Planning how to answer...")

            state: dict[str, Any] = {}
            async for mode, chunk in graph.astream(
                {"question": self.message, "history": history},
                config={"recursion_limit": RECURSION_LIMIT},
                stream_mode=["updates", "custom"],
            ):
                if mode == "custom":
                    yield progress(describe(chunk), {**chunk, "thread_id": self.thread_id})
                    continue
                for update in chunk.values():
                    for key, value in (update or {}).items():
                        if key == "findings":
                            state.setdefault("findings", []).extend(value)
                        else:
                            state[key] = value

            result = self._result(state, evidence)
            _record(self.thread_id, "assistant", result["answer"], payload=result, job_id=self.job_id)
            yield completed("Answer ready", result)
        except Exception as exc:
            logger.exception("Assistant turn failed for thread %s", self.thread_id)
            yield error(f"Assistant error: {exc}", fatal=True)

    def _result(self, state: dict[str, Any], evidence: EvidenceLog) -> dict[str, Any]:
        cited = state.get("cited", [])
        critique = state.get("critique", {})
        insufficient = bool(state.get("insufficient_evidence"))
        return {
            "thread_id": self.thread_id,
            "question": self.message,
            "answer": state.get("draft", ""),
            "insufficient_evidence": insufficient,
            "grounded": insufficient or bool(cited),
            "citations": [
                item.as_dict() for item in (evidence.get(evidence_id) for evidence_id in cited) if item
            ],
            "plan": state.get("plan", {}),
            "findings": state.get("findings", []),
            "critique": critique,
            "revisions": state.get("revisions", 0),
            # Problems the critic still saw when the revision cap stopped it.
            "unresolved": critique.get("problems", []) if critique.get("verdict") == "revise" else [],
            "evidence_gathered": len(evidence),
        }
