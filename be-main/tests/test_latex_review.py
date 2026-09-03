"""Repair of LLM-generated review LaTeX.

Each case here is drift a real model produced, not a hypothetical: a local
qwen2.5:7b review loaded biblatex, used the plain style, and left its BibTeX
entries after \end{document}, which made the document fail to compile at all.
"""

from utils.latex_review import normalize_review_latex

DRIFTED = r"""\documentclass{article}
\usepackage{hyperref}
\usepackage{biblatex}
\addbibresource{references.bib}

\begin{document}
Body citing \cite{a1}.
\bibliographystyle{plain}
\bibliography{references}
\end{document}

% references.bib
@article{a1,
    author = {A. Author},
    title = {{A paper about {Braces} inside}},
    year = {2020}
}
"""


class TestNormalizeReviewLatex:
    def test_moves_entries_into_filecontents_before_documentclass(self):
        out = normalize_review_latex(DRIFTED)
        bib = out.index("filecontents")
        assert bib < out.index("\\documentclass")
        assert "@article{a1," in out

    def test_nothing_survives_after_end_document(self):
        # TeX never reads it, so a bibliography left there is silently lost.
        out = normalize_review_latex(DRIFTED)
        assert out.split("\\end{document}")[-1].strip() == ""

    def test_replaces_biblatex_with_natbib(self):
        out = normalize_review_latex(DRIFTED)
        assert "biblatex" not in out
        assert "addbibresource" not in out
        assert "\\usepackage{natbib}" in out

    def test_upgrades_the_bibliography_style(self):
        assert "\\bibliographystyle{plainnat}" in normalize_review_latex(DRIFTED)

    def test_handles_nested_braces_in_entries(self):
        out = normalize_review_latex(DRIFTED)
        assert "{{A paper about {Braces} inside}}" in out

    def test_is_idempotent(self):
        once = normalize_review_latex(DRIFTED)
        assert normalize_review_latex(once) == once

    def test_leaves_a_correct_document_alone(self):
        good = (
            "\\begin{filecontents*}{references.bib}\n"
            "@article{k, author = {A}, title = {T}, year = {2020}}\n"
            "\\end{filecontents*}\n"
            "\\documentclass{article}\n\\usepackage{natbib}\n"
            "\\begin{document}\n\\cite{k}\n"
            "\\bibliographystyle{plainnat}\n\\bibliography{references}\n"
            "\\end{document}\n"
        )
        assert normalize_review_latex(good).strip() == good.strip()

    def test_converts_printbibliography(self):
        src = (
            "\\documentclass{article}\n\\usepackage{biblatex}\n"
            "\\begin{document}\n\\printbibliography\n\\end{document}\n"
        )
        out = normalize_review_latex(src)
        assert "\\printbibliography" not in out
        assert "\\bibliography{references}" in out

    def test_adds_a_bibliography_when_entries_would_go_unprinted(self):
        src = (
            "\\documentclass{article}\n\\begin{document}\nBody \\cite{k}.\n"
            "\\end{document}\n@article{k, author = {A}, title = {T}, year = {2020}}\n"
        )
        out = normalize_review_latex(src)
        assert "\\bibliography{references}" in out
        assert out.index("\\bibliography{references}") < out.index("\\end{document}")

    def test_empty_input_is_returned_unchanged(self):
        assert normalize_review_latex("") == ""
        assert normalize_review_latex("   ") == "   "
