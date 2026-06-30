CANONICAL_DEFAULT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "canonical_normalization",
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
                        "solve or investigate, not how they solve it and not the results."
                    ),
                },
                "methods": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": (
                            "A 2-element array [normalized_term, original_text]. "
                            "normalized_term: a canonical, reusable label for the method, at most 5 words, "
                            "lowercase snake_case (for example 'stacked_hourglass_network', 'intermediate_supervision'). "
                            "It should identify the method or model in a way that can match the same method in other papers, "
                            "collapsing trivial naming variants. "
                            "original_text: a short phrase taken from the paper (verbatim or lightly paraphrased) that "
                            "describes the method as used in this work."
                        ),
                    },
                    "description": (
                        "Key methods, models, algorithms, or experimental techniques that the authors actually use to "
                        "address the stated problem. Each array element is [normalized_term, original_text] as described "
                        "above. Only include methods that are clearly used in the authors' own approach or experiments, "
                        "not generic background methods mentioned in related work."
                    ),
                },
                "datasets": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": (
                            "A 2-element array [normalized_term, original_text]. "
                            "normalized_term: a canonical dataset identifier, at most 5 words, lowercase snake_case "
                            "(for example 'mpii_human_pose', 'coco', 'human36m'). It should unify trivial naming variants "
                            "of the same dataset across papers. "
                            "original_text: the dataset name or description as given in this paper (verbatim or lightly "
                            "cleaned)."
                        ),
                    },
                    "description": (
                        "Datasets that the authors use, create, or report empirical results on. Prefer one entry per "
                        "distinct dataset. Each array element is [normalized_term, original_text] as described above. "
                        "Include public benchmarks and named internal datasets if they are used in experiments or "
                        "evaluation. Do not include vague phrases such as 'synthetic data' unless they are presented as "
                        "a named dataset in the text."
                    ),
                },
                "assumptions_explicit": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": (
                            "A 2-element array [normalized_term, original_text]. "
                            "normalized_term: a short, general label for the explicit assumption, at most 5 words, "
                            "lowercase snake_case (for example 'centered_person_input', 'iid_samples', "
                            "'gaussian_noise_assumption'). It should capture the core assumption category in a way that "
                            "could be reused when other papers make the same type of assumption. "
                            "original_text: the assumption as stated in the paper (verbatim or lightly paraphrased)."
                        ),
                    },
                    "description": (
                        "Assumptions that the authors clearly and directly state in the text. Each array element is "
                        "[normalized_term, original_text] as described above. Every item must be traceable to explicit "
                        "wording such as 'we assume', 'we suppose', 'we restrict ourselves to', or equivalent phrasing."
                    ),
                },
                "assumptions_implicit": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": (
                            "A 2-element array [normalized_term, original_text]. "
                            "normalized_term: a compact, reusable label for the implicit assumption, at most 5 words, "
                            "lowercase snake_case (for example 'sufficient_labeled_data', 'centered_person_required', "
                            "'rgb_input_only'). It should describe the assumption category in a way that can group similar "
                            "assumptions across different papers. "
                            "original_text: a short phrase summarizing how this assumption is reflected in this specific "
                            "paper, grounded in its wording."
                        ),
                    },
                    "description": (
                        "Assumptions that are not explicitly labeled as assumptions but are clearly required for the "
                        "method, setup, or conclusions to make sense. Each array element is [normalized_term, original_text] "
                        "as described above. Items must be grounded in the text and represent reasonable, non-speculative "
                        "inferences."
                    ),
                },
                "limitations_explicit": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": (
                            "A 2-element array [normalized_term, original_text]. "
                            "normalized_term: a general limitation category, at most 5 words, lowercase snake_case "
                            "(for example 'single_person_only', 'limited_dataset_scope', 'occlusion_sensitivity'). It should "
                            "capture a limitation type that can also appear in other papers. "
                            "original_text: the limitation as explicitly acknowledged by the authors in this paper "
                            "(verbatim or lightly paraphrased)."
                        ),
                    },
                    "description": (
                        "Limitations or weaknesses explicitly acknowledged by the authors. Each array element is "
                        "[normalized_term, original_text] as described above. Items must correspond to clearly signaled "
                        "limitations such as 'a limitation of our work', 'we only evaluate on', or similar phrasing."
                    ),
                },
                "limitations_implied": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": (
                            "A 2-element array [normalized_term, original_text]. "
                            "normalized_term: a concise, reusable label for the implied limitation, at most 5 words, "
                            "lowercase snake_case (for example 'performance_drops', 'occlusion_sensitivity', "
                            "'single_person_only', 'high_gpu_requirements'). It should generalize the specific wording into a "
                            "category that can match similar limitations across papers. For example, 'Performance drops on "
                            "heavily occluded joints' can be normalized to 'performance_drops'. "
                            "original_text: a short phrase describing the limitation as implied by this paper's setup, "
                            "results, or scope, grounded in the text."
                        ),
                    },
                    "description": (
                        "Limitations that are not explicitly labeled as limitations by the authors but can be reasonably "
                        "inferred from the described setup, scope, or results. Each array element is "
                        "[normalized_term, original_text] as described above. Items must be concrete and grounded in "
                        "specific details, not vague criticism."
                    ),
                },
                "future_work": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": (
                            "A 2-element array [normalized_term, original_text]. "
                            "normalized_term: a short, reusable label for the future work direction, at most 5 words, "
                            "lowercase snake_case (for example 'extend_to_multi_person', 'add_temporal_modeling', "
                            "'evaluate_on_more_datasets'). It should capture the general research direction that could also "
                            "appear in other papers. "
                            "original_text: the future work idea as stated in this paper (verbatim or lightly paraphrased)."
                        ),
                    },
                    "description": (
                        "Future work directions, open problems, or extensions that the authors clearly present as work to be "
                        "done after this paper. Each array element is [normalized_term, original_text] as described above. "
                        "Do not invent future work ideas that the authors did not indicate."
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
        }
    }
}
