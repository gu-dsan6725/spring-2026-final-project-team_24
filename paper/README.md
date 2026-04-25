# Paper

The conference-format paper (8-12 pages excluding references).

## Expected artifacts

- `report.pdf` — final rendered paper (the submission artifact).
- `report-draft.qmd` — Quarto source.
- `references.bib` — citations (see also `../backend/references/`).
- `figures/` — generated diagrams, screenshots, plots (created by the renderer when needed).

## Re-render

```bash
cd submission/team_24/paper
quarto render report-draft.qmd --to pdf
```

Quarto's `output-file: report` directive in the YAML header produces
`report.pdf` directly (so the source-vs-final names are stable).

## Outline (per `deliverables.md`)

1. Title and Abstract
2. Introduction
3. Related Work
4. System Architecture — agent types, coordination, external APIs
5. Data and Evaluation — sources, preprocessing, metrics, benchmarks
6. Models and Technologies — LLMs, frameworks, deployment
7. Responsible AI Considerations
8. Findings and Discussion
9. Conclusion and Future Work
10. References

## Notes

Architecture material for sections 4–5 is already captured in
`../backend/notes/` (module-level design docs) and
`../backend/evals/` (offline evaluation harness + sample runs). The
paper should cite and condense these rather than duplicating them.
