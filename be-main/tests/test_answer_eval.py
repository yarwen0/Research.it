"""Scoring for the answer benchmark in evals/answers, without a model.

The benchmark runs against a live model, so it is recorded rather than gated.
These pin the scoring it reports, and keep its questions tied to the labels
the retrieval benchmark already validates.
"""

from __future__ import annotations

import json

import pytest

from evals.answers.harness import cites_evidence, load_questions, score, states_fact, summarize
from evals.retrieval.harness import QUESTIONS_PATH as RETRIEVAL_QUESTIONS


def _answer(text="", *, declined=False, grounded=True, cited=(), dropped=(), latency=1000.0):
    return {
        "answer": text,
        "insufficient_evidence": declined,
        "grounded": grounded,
        "dropped_citations": list(dropped),
        "cited_texts": list(cited),
        "latency_ms": latency,
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }


LOOKUP = {
    "id": "h01",
    "answerable": True,
    "question": "What learning rate?",
    "expect_any": ["2.5e-4", "0.00025"],
    "evidence": [{"paper": "hourglass", "text": "learning rate of 2.5e-4"}],
}
UNANSWERABLE = {"id": "u01", "answerable": False, "question": "What is the carbon footprint?"}


class TestStatesFact:
    def test_any_listed_spelling_counts_ignoring_case_and_spacing(self):
        assert states_fact("Trained at  2.5E-4.", LOOKUP)
        assert states_fact("A rate of 0.00025.", LOOKUP)

    def test_a_missing_fact(self):
        assert not states_fact("Trained with rmsprop.", LOOKUP)

    def test_expect_all_needs_every_fact(self):
        question = {"expect_all": ["S9", "S11"]}
        assert states_fact("Subjects S9 and S11 are held out.", question)
        assert not states_fact("Subject S9 is held out.", question)


class TestCitesEvidence:
    def test_a_cited_passage_containing_the_evidence(self):
        assert cites_evidence(["We use rmsprop with a learning rate of 2.5e-4."], LOOKUP)

    def test_citing_something_else_does_not_count(self):
        assert not cites_evidence(["Training takes about 3 days."], LOOKUP)
        assert not cites_evidence([], LOOKUP)


class TestScore:
    def test_a_correct_supported_answer(self):
        verdict = score(LOOKUP, _answer("2.5e-4 [S1]", cited=["a learning rate of 2.5e-4 here"]))
        assert verdict["correct"] and verdict["supported"]

    def test_a_correct_but_uncited_answer_is_not_supported(self):
        # The pattern the first live run found ten times.
        verdict = score(LOOKUP, _answer("2.5e-4", grounded=False))
        assert verdict["correct"]
        assert not verdict["supported"]

    def test_declining_an_answerable_question_is_wrong_whatever_it_says(self):
        verdict = score(LOOKUP, _answer("Maybe 2.5e-4, the sources are unclear.", declined=True))
        assert not verdict["correct"]

    def test_declining_an_unanswerable_question_is_right(self):
        assert score(UNANSWERABLE, _answer("The sources do not say.", declined=True))["correct"]
        assert not score(UNANSWERABLE, _answer("About 50 kg of CO2."))["correct"]


class TestSummarize:
    def test_answerable_and_unanswerable_are_reported_apart(self):
        verdicts = [
            score(LOOKUP, _answer("2.5e-4", cited=["learning rate of 2.5e-4"], latency=1000)),
            score(LOOKUP, _answer("no idea", declined=True, latency=3000)),
            score(UNANSWERABLE, _answer("Not in the sources.", declined=True, dropped=["S9"], latency=2000)),
        ]
        summary = summarize(verdicts)
        assert summary["answerable"] == {
            "count": 2,
            "correct": 0.5,
            "supported_by_citation": 0.5,
            "declined_wrongly": 0.5,
        }
        assert summary["unanswerable"] == {"count": 1, "declined": 1.0}
        assert summary["dropped_citations"] == 1
        assert summary["latency_ms_p50"] == pytest.approx(2000.0)

    def test_citing_every_supplied_passage_is_reported(self):
        # Such an answer is "supported" whatever it says, so the breadth has
        # to be visible beside that rate.
        everything = _answer("2.5e-4", cited=["learning rate of 2.5e-4", "other", "more"])
        everything["sources_supplied"] = 3
        one = _answer("2.5e-4", cited=["learning rate of 2.5e-4"])
        one["sources_supplied"] = 3
        summary = summarize([score(LOOKUP, everything), score(LOOKUP, one)])
        assert summary["answerable"]["supported_by_citation"] == 1.0
        assert summary["citations"] == {"mean_sources_cited": 2.0, "cited_every_source": 0.5}


class TestQuestionSet:
    @pytest.fixture(scope="class")
    def questions(self):
        return load_questions()

    def test_size_and_mix(self, questions):
        assert len(questions) == 26
        assert sum(q["answerable"] for q in questions) == 18

    def test_answerable_questions_are_the_retrieval_benchmarks_word_for_word(self, questions):
        # Their evidence labels are then the ones the retrieval benchmark's
        # label check already proves present in the papers.
        retrieval = {q["id"]: q for q in json.loads(RETRIEVAL_QUESTIONS.read_text())}
        for question in (q for q in questions if q["answerable"]):
            assert question["question"] == retrieval[question["id"]]["question"]
            assert question["evidence"] == retrieval[question["id"]]["evidence"]

    def test_every_answerable_question_says_what_a_right_answer_contains(self, questions):
        for question in (q for q in questions if q["answerable"]):
            assert question.get("expect_any") or question.get("expect_all"), question["id"]

    def test_unanswerable_questions_carry_no_answer(self, questions):
        for question in (q for q in questions if not q["answerable"]):
            assert not {"evidence", "expect_any", "expect_all"} & set(question), question["id"]
