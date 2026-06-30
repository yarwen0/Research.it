import uuid
import json

from core import OpenRouterClient, PDFExtractor, OntologyStorage, CorpusStorage

if __name__ == "__main__":
    from config import OPENROUTER_API_KEY

    llm_client = OpenRouterClient(
        api_key=OPENROUTER_API_KEY,
        model="openai/gpt-oss-20b:free",
    )
    extractor = PDFExtractor(llm_client=llm_client)
    ontology_store = OntologyStorage()
    corpus_store = CorpusStorage()

    # Get arguments from terminal, the first argument is the text file name
    import sys
    if len(sys.argv) != 2:
        print("Usage: python extractor_example.py <text_file>")
        sys.exit(1)

    text_file = sys.argv[1]
    with open(f"./examples/docs/{text_file}.txt", "r", encoding="utf-8") as f:
        text = f.read()
    
    extraction_result = extractor.extract_from_raw_text(text)

    # Getting existing ontology
    parameters = [
        "methods",
        "datasets",
        "assumptions_explicit",
        "assumptions_implicit",
        "limitations_explicit",
        "limitations_implied",
        "future_work",
    ]
    existing_ontology = ontology_store.get_ontology_for_llm(parameters)
    print(existing_ontology)

    normalized_result = extractor.normalize_extracted_parameters(extraction_result, existing_ontology=existing_ontology) # type: ignore
    print("Normalized Extraction Result:")
    print(normalized_result)
    normalized_payload = json.loads(normalized_result)
    paper_uuid = uuid.uuid4().hex
    ontology_store.map_to_ontology(normalized_payload, paper_uuid)
    corpus_store.upsert_paper(paper_uuid, normalized_payload)
