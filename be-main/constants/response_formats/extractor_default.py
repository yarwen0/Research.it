EXTRACTOR_DEFAULT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "research_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "problem": {
                    "type": "string",
                    "description": (
                        "A single, concise description of the main research or technical problem that the text "
                        "claims to address. This must be derived directly from the text (for example, from the "
                        "title, abstract, or introduction) and should summarize what the authors are trying to "
                        "solve or investigate, not how they solve it and not the results. If multiple problems "
                        "are mentioned, focus on the primary one that the work centers on."
                    ),
                },
                "methods": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Key methods, models, algorithms, or experimental techniques that the authors actually "
                        "apply to address the stated problem. Each item must be a short, self-contained phrase "
                        "naming a single method (for example 'BERT fine-tuning', 'Monte Carlo simulation', "
                        "'randomized controlled trial', 'ResNet-50 backbone'). Only include methods that are "
                        "clearly used in the authors' own approach or experiments. Do not list generic background "
                        "methods that are only mentioned in related work or cited papers and not used in this study."
                    ),
                },
                "datasets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Datasets that the authors use, create, or report empirical results on. Prefer one entry "
                        "per distinct dataset. Use the dataset name as given in the text or a clearly equivalent "
                        "canonical form when the text provides it (for example 'Human3.6M', 'COCO', 'MPII Human "
                        "Pose', 'nasa_rockets_cnn'). Include public benchmarks and named internal datasets if they "
                        "are used in experiments or evaluation. Do not include generic phrases such as 'synthetic "
                        "data' or 'simulated data' unless they are explicitly presented as a named dataset."
                    ),
                },
                "assumptions_explicit": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Assumptions that the authors clearly and directly state in the text. Each item should "
                        "correspond to an assumption that could be traced back to a specific sentence or passage "
                        "with words such as 'assume', 'we suppose', 'we consider', 'we restrict ourselves to', or "
                        "equivalent phrasing. Paraphrasing is allowed, but the content must be explicitly supported "
                        "by the text and not inferred by you."
                    ),
                },
                "assumptions_implicit": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Assumptions that are not explicitly named as assumptions but are clearly required for the "
                        "method, experimental setup, or conclusions to make sense. These should be reasonable, "
                        "text-backed inferences about what must be true for the approach to work (for example, "
                        "availability of sufficiently large labeled data, specific properties of noise, or "
                        "constraints on the input distribution), even if the authors never write the word "
                        "'assume'. Do not list speculative or far-fetched guesses that are not grounded in the text."
                    ),
                },
                "limitations_explicit": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Limitations, weaknesses, or constraints of the work that the authors themselves explicitly "
                        "acknowledge. Each item must correspond to a point that appears in the text with phrases such "
                        "as 'a limitation of our work', 'we only evaluate on', 'our method does not handle', "
                        "'this study is restricted to', or similar language that clearly signals a limitation. "
                        "Paraphrase these statements concisely while preserving their technical meaning."
                    ),
                },
                "limitations_implied": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Limitations that are not explicitly labeled as limitations by the authors but can be "
                        "reasonably inferred from the described setup, scope, or results. Examples include narrow "
                        "domains, small sample sizes, limited baselines, restricted evaluation settings, or strong "
                        "simplifying assumptions that reduce generality. These items must be grounded in specific "
                        "details from the text and should describe concrete constraints, not vague criticism or "
                        "speculation."
                    ),
                },
                "future_work": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Future work directions, open problems, or extensions that the authors clearly present as "
                        "work to be done after this paper. Each item should correspond to a concrete suggestion or "
                        "future direction mentioned with phrases such as 'in future work', 'we plan to', 'an "
                        "interesting direction is', or similar wording. You may paraphrase these, but they must be "
                        "rooted in the text. Do not invent new future work ideas that the authors did not clearly "
                        "indicate."
                    ),
                },
            },
            "required": [
                "problem",
                "methods",
                "datasets",
                "assumptions_explicit",
                "limitations_explicit",
                "future_work",
                "limitations_implied",
            ],
        },
    },
}
