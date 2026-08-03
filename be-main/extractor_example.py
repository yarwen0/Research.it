"""Run the extraction → normalization → ontology pipeline over one local text file.

    python extractor_example.py dreampose

Writes into a throwaway project so the example never mixes its terms into a
real run's ontology.
"""

import json
import sys
import uuid

from core import PDFExtractor, create_llm_client
from db.repositories import OntologyRepository, ProjectRepository
from db.session import session_scope

PARAMETERS = [
    "methods",
    "datasets",
    "assumptions_explicit",
    "assumptions_implicit",
    "limitations_explicit",
    "limitations_implied",
    "future_work",
]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python extractor_example.py <text_file>")
        sys.exit(1)

    text_file = sys.argv[1]
    with open(f"./examples/docs/{text_file}.txt", encoding="utf-8") as f:
        text = f.read()

    extractor = PDFExtractor(llm_client=create_llm_client())

    project_id = uuid.uuid4().hex
    paper_id = uuid.uuid4().hex

    with session_scope() as session:
        ProjectRepository(session).create(project_id, f"example: {text_file}")

    extraction_result = extractor.extract_from_raw_text(text)

    with session_scope() as session:
        existing_ontology = OntologyRepository(session, project_id).terms_for(PARAMETERS)
    print("Existing ontology:", existing_ontology)

    normalized_result = extractor.normalize_extracted_parameters(
        extraction_result, existing_ontology=existing_ontology  # type: ignore[arg-type]
    )
    print("Normalized Extraction Result:")
    print(normalized_result)

    normalized_payload = json.loads(normalized_result)
    with session_scope() as session:
        OntologyRepository(session, project_id).map_paper(normalized_payload, paper_id)

    print(f"Stored under project {project_id}")
