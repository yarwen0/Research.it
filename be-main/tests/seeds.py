"""Projects seeded straight into the database, for tests that need real rows.

Built through the same repositories the pipeline writes with, so the shapes
match what a research run leaves behind.
"""

from __future__ import annotations

import uuid

from db.repositories import GraphRepository, OntologyRepository, ProjectRepository
from db.session import session_scope
from retrieval.indexer import PaperIndexer
from tests.fakes import HashingEmbedder

HOURGLASS = {
    "paper_id": "1603.06937",
    "title": "Stacked Hourglass Networks for Human Pose Estimation",
    "authors": ["Alejandro Newell"],
    "normalized": {
        "problem": "2d_pose_estimation",
        "methods": [["stacked_hourglass", "Stacked hourglass network"]],
        "datasets": [["mpii", "MPII Human Pose"], ["flic", "FLIC"]],
        "limitations_explicit": [["occlusion", "Struggles with heavy occlusion"]],
        "future_work": [["multi_person", "Handle multiple people"]],
    },
    "references": [{"title": "Deep Residual Learning for Image Recognition"}],
}
DREAMPOSE = {
    "paper_id": "2511.09502",
    "title": "DreamPose3D: Hallucinative Diffusion",
    "authors": ["Jerrin Bright"],
    "normalized": {
        "problem": "2d_pose_estimation",
        "methods": [["diffusion_model", "Diffusion model"]],
        "datasets": [["human36m", "Human3.6M"]],
        "limitations_explicit": [["occlusion", "Fails under high occlusion"]],
        "future_work": [["physics_priors", "Physics-based priors"]],
    },
    "references": [
        {"title": "Deep Residual Learning for Image Recognition"},
        {"title": "Denoising Diffusion Probabilistic Models"},
    ],
}
TEXTS = {
    "1603.06937": "3.4 Training Details\nWe use rmsprop with a learning rate of 2.5e-4 on MPII.",
    "2511.09502": "B Implementation Details\nDreamPose3D is optimized with AdamW on Human3.6M.",
}


def seed_pose_project() -> str:
    """Two processed papers with records, ontology terms, citations and passages."""
    project = uuid.uuid4().hex
    with session_scope() as session:
        ProjectRepository(session).create(project, "pose estimation")
        GraphRepository(session, project).build_from_processed_papers([HOURGLASS, DREAMPOSE])
        for paper in (HOURGLASS, DREAMPOSE):
            OntologyRepository(session, project).map_paper(paper["normalized"], paper["paper_id"])
    indexer = PaperIndexer(HashingEmbedder())
    for paper in (HOURGLASS, DREAMPOSE):
        indexer.index_paper(project, paper, TEXTS[paper["paper_id"]])
    return project
