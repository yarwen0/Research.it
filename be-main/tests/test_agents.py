"""The assistant's tools, its ReAct loop, and the graph that runs them.

A scripted model stands in for the LLM. Its replies are computed from each
request — the schema asked for, the specialist's role — because specialists
run in parallel threads and their calls arrive in no fixed order.
"""

from __future__ import annotations

import pytest

from agents.graph import MAX_REVISIONS, AssistantDeps, build_graph
from agents.react import parse_json_object, parse_step, run_react, step_format
from agents.tools import EvidenceLog, ProjectTools, Tool
from telemetry import collect_usage
from tests.fakes import (
    FakeLLMClient,
    HashingEmbedder,
    agent_responder,
    react_step,
    schema_name,
)
from tests.seeds import seed_pose_project


@pytest.fixture(scope="module")
def project_id() -> str:
    return seed_pose_project()


@pytest.fixture
def tools(project_id) -> ProjectTools:
    return ProjectTools(project_id, HashingEmbedder(), EvidenceLog())


class TestTools:
    def test_search_registers_each_passage_as_evidence(self, tools):
        result = tools.search_passages({"query": "rmsprop learning rate", "top": 2})
        assert result.startswith("[E1] ")
        assert "2.5e-4" in result
        assert tools.evidence.get("E1").kind in ("passage",)

    def test_the_same_passage_keeps_its_id(self, tools):
        tools.search_passages({"query": "rmsprop", "top": 1})
        before = len(tools.evidence)
        tools.search_passages({"query": "rmsprop", "top": 1})
        assert len(tools.evidence) == before

    def test_search_needs_a_query(self, tools):
        assert "needs a query" in tools.search_passages({})

    def test_paper_record_by_id_and_by_title(self, tools):
        by_id = tools.paper_record({"paper_id": "1603.06937"})
        by_title = tools.paper_record({"paper_id": "hourglass"})
        assert "MPII Human Pose (mpii)" in by_id
        assert by_id == by_title  # the same record, and the same evidence id

    def test_paper_record_for_an_unknown_paper(self, tools):
        assert "No processed paper matches" in tools.paper_record({"paper_id": "nope"})

    def test_papers_using_a_dataset(self, tools):
        result = tools.papers_using({"term": "human3.6m", "field": "datasets"})
        assert "DreamPose3D" in result
        assert "Hourglass" not in result

    def test_papers_using_matches_the_canonical_form_too(self, tools):
        assert "Stacked Hourglass" in tools.papers_using({"term": "stacked_hourglass"})

    def test_research_gaps_from_the_symbolic_finder(self, tools):
        result = tools.research_gaps({})
        assert "[E1]" in result
        assert "gap type" in result
        assert tools.evidence.get("E1").kind == "gap"

    def test_research_gaps_by_type(self, tools):
        result = tools.research_gaps({"gap_type": "limitation_gap"})
        assert all("limitation_gap" in line for line in result.splitlines())

    def test_citation_stats_counts_shared_references(self, tools):
        first = tools.citation_stats({"top": 1}).splitlines()[0]
        assert "Deep Residual Learning" in first
        assert "cited by 2" in first


def _echo_tool(name="lookup", fail=False):
    def run(args):
        if fail:
            raise RuntimeError("index offline")
        return f"[E1] result for {args.get('query')}"

    return Tool(name, "Looks things up.", {"query": "what"}, run)


class TestReact:
    def test_calls_a_tool_then_finishes(self):
        llm = FakeLLMClient(
            [react_step("lookup", query="pose"), react_step("finish", answer="Pose is covered [E1].")]
        )
        events = []
        result = run_react(
            llm,
            role="literature",
            instructions="",
            question="q",
            task="t",
            tools={"lookup": _echo_tool()},
            emit=events.append,
        )
        assert result.findings == "Pose is covered [E1]."
        assert result.actions == ["lookup"]
        assert [e["type"] for e in events] == ["tool_call", "observation"]
        assert events[0]["arguments"] == {"query": "pose"}
        assert events[1]["evidence"] == ["E1"]

    def test_the_observation_is_fed_back(self):
        llm = FakeLLMClient(
            [react_step("lookup", query="pose"), react_step("finish", answer="done [E1]")]
        )
        run_react(
            llm, role="r", instructions="", question="q", task="t",
            tools={"lookup": _echo_tool()}, emit=lambda e: None,
        )
        last_request = llm.requests[-1][0]
        assert last_request[-1]["content"] == "Result of lookup:\n[E1] result for pose"

    def test_an_uncited_finish_after_evidence_is_sent_back_once(self):
        llm = FakeLLMClient(
            [
                react_step("lookup", query="pose"),
                react_step("finish", answer="I found passages; now I will analyse them."),
                react_step("finish", answer="Pose datasets are covered [E1]."),
            ]
        )
        events = []
        result = run_react(
            llm, role="literature", instructions="", question="q", task="t",
            tools={"lookup": _echo_tool()}, emit=events.append,
        )
        assert result.findings == "Pose datasets are covered [E1]."
        assert "cites no evidence" in llm.requests[-1][0][-1]["content"]
        assert {"type": "self_check", "specialist": "literature", "problem": "findings cited no evidence"} in events

    def test_the_nudge_is_given_only_once(self):
        llm = FakeLLMClient(
            [
                react_step("lookup", query="pose"),
                react_step("finish", answer="still nothing"),
                react_step("finish", answer="still nothing, again"),
            ]
        )
        result = run_react(
            llm, role="r", instructions="", question="q", task="t",
            tools={"lookup": _echo_tool()}, emit=lambda e: None,
        )
        assert result.findings == "still nothing, again"
        assert len(llm.requests) == 3

    def test_no_nudge_when_the_tools_found_nothing(self):
        def empty(_args):
            return "No passages matched."

        llm = FakeLLMClient([react_step("lookup", query="x"), react_step("finish", answer="Nothing relevant.")])
        result = run_react(
            llm, role="r", instructions="", question="q", task="t",
            tools={"lookup": Tool("lookup", "d", {}, empty)}, emit=lambda e: None,
        )
        assert result.findings == "Nothing relevant."
        assert len(llm.requests) == 2

    def test_an_unknown_tool_is_reported_not_fatal(self):
        llm = FakeLLMClient([react_step("teleport"), react_step("finish", answer="ok")])
        result = run_react(
            llm, role="r", instructions="", question="q", task="t",
            tools={"lookup": _echo_tool()}, emit=lambda e: None,
        )
        assert result.findings == "ok"
        assert "There is no tool called 'teleport'" in llm.requests[-1][0][-1]["content"]

    def test_a_failing_tool_is_an_observation(self):
        llm = FakeLLMClient([react_step("lookup", query="x"), react_step("finish", answer="tried")])
        run_react(
            llm, role="r", instructions="", question="q", task="t",
            tools={"lookup": _echo_tool(fail=True)}, emit=lambda e: None,
        )
        assert "lookup failed: index offline" in llm.requests[-1][0][-1]["content"]

    def test_the_step_budget_forces_a_finish(self):
        replies = [react_step("lookup", query="again")] * 3 + [react_step("finish", answer="out of steps")]
        llm = FakeLLMClient(replies)
        result = run_react(
            llm, role="r", instructions="", question="q", task="t",
            tools={"lookup": _echo_tool()}, emit=lambda e: None, max_steps=3,
        )
        assert result.findings == "out of steps"
        # The last call's schema allows nothing but finishing.
        final_schema = llm.requests[-1][1]["json_schema"]["schema"]
        assert final_schema["properties"]["action"]["enum"] == ["finish"]

    def test_unparseable_output_finishes_with_the_text(self):
        llm = FakeLLMClient(["I think the answer is 42."])
        result = run_react(
            llm, role="r", instructions="", question="q", task="t",
            tools={"lookup": _echo_tool()}, emit=lambda e: None,
        )
        assert result.findings == "I think the answer is 42."

    def test_step_schema_names_every_action(self):
        schema = step_format(["lookup", "finish"])["json_schema"]["schema"]
        assert schema["properties"]["action"]["enum"] == ["lookup", "finish"]
        assert schema["required"] == ["thought", "action"]

    def test_parsers(self):
        assert parse_json_object('noise {"a": 1} noise') == {"a": 1}
        assert parse_json_object("no json") is None
        assert parse_step("not json")["action"] == "finish"


def _run(project_id, llm, question="What learning rate does the hourglass network use?"):
    evidence = EvidenceLog()
    deps = AssistantDeps(llm, ProjectTools(project_id, HashingEmbedder(), evidence), evidence)
    events, final = [], {}
    for mode, chunk in build_graph(deps).stream(
        {"question": question, "history": ""}, stream_mode=["updates", "custom"]
    ):
        if mode == "custom":
            events.append(chunk)
        else:
            for update in chunk.values():
                final.update(update or {})
    return final, events, evidence


class TestGraph:
    def test_delegates_writes_and_accepts(self, project_id):
        llm = FakeLLMClient(respond=agent_responder(plan={"literature": "find the learning rate"}))
        final, events, evidence = _run(project_id, llm)

        assert final["plan"] == {"literature": "find the learning rate"}
        assert final["draft"] == "Hourglass uses rmsprop [E1]."
        assert final["cited"] == ["E1"]
        assert final["critique"]["verdict"] == "accept"
        assert [e["type"] for e in events] == [
            "plan", "tool_call", "observation", "finding", "draft", "critique",
        ]
        assert evidence.get("E1").kind == "passage"

    def test_the_writer_sees_evidence_no_finding_cited(self, project_id):
        """A specialist that found the right passages but reported them badly
        must not keep them from the writer."""

        def respond(messages, response_format):
            name = schema_name(response_format)
            if name == "react_step":
                if "Result of" in messages[-1]["content"] or "cites no evidence" in messages[-1]["content"]:
                    return react_step("finish", answer="Now I will analyse these.")
                return react_step("search_passages", query="rmsprop learning rate")
            return agent_responder(plan={"literature": "x"})(messages, response_format)

        llm = FakeLLMClient(respond=respond)
        _run(project_id, llm)
        writer_prompt = next(m for m, f in llm.requests if schema_name(f) == "assistant_answer")
        assert "2.5e-4" in writer_prompt[-1]["content"]

    def test_specialists_run_only_when_delegated_to(self, project_id):
        llm = FakeLLMClient(
            respond=agent_responder(plan={"literature": "methods", "gaps": "open gaps"})
        )
        _, events, _ = _run(project_id, llm)
        finished = {e["specialist"] for e in events if e["type"] == "finding"}
        assert finished == {"literature", "gaps"}

    def test_an_empty_plan_falls_back_to_literature(self, project_id):
        llm = FakeLLMClient(respond=agent_responder(plan={}))
        final, _, _ = _run(project_id, llm, question="Anything?")
        assert final["plan"] == {"literature": "Anything?"}

    def test_a_rejected_draft_is_revised_once(self, project_id):
        llm = FakeLLMClient(respond=agent_responder(plan={"literature": "x"}, critiques=["revise", "revise"]))
        final, events, _ = _run(project_id, llm)

        drafts = [e for e in events if e["type"] == "draft"]
        assert [d["revision"] for d in drafts] == list(range(MAX_REVISIONS + 1))
        # The cap stopped it, with the critic still unsatisfied.
        assert final["critique"]["verdict"] == "revise"
        revision_prompt = [m for m, f in llm.requests if schema_name(f) == "assistant_answer"][-1]
        assert "A reviewer rejected your previous draft" in revision_prompt[-1]["content"]

    def test_an_uncited_draft_is_sent_back_without_asking_the_critic(self, project_id):
        llm = FakeLLMClient(respond=agent_responder(plan={"literature": "x"}, answer="No citations here."))
        final, events, _ = _run(project_id, llm)

        critiques = [e for e in events if e["type"] == "critique"]
        assert all(c["by"] == "rules" for c in critiques)
        assert "critique" not in llm.schema_names()
        assert final["critique"]["problems"] == ["No statement cites evidence."]

    def test_an_invented_citation_is_dropped_and_flagged(self, project_id):
        llm = FakeLLMClient(
            respond=agent_responder(plan={"literature": "x"}, answer="It uses rmsprop [E1][E99].")
        )
        final, events, _ = _run(project_id, llm)
        first_critique = next(e for e in events if e["type"] == "critique")
        assert "E99" in first_critique["problems"][0]
        assert "[E99]" not in final["draft"]

    def test_every_call_is_attributed_to_its_agent_stage(self, project_id):
        llm = FakeLLMClient(respond=agent_responder(plan={"literature": "x", "citations": "y"}))
        with collect_usage() as usage:
            _run(project_id, llm)
        stages = {call.stage for call in usage.calls}
        assert {"agent.plan", "agent.literature", "agent.citations", "agent.write", "agent.critique"} <= stages
