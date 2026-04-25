# Project Website

Quarto / MkDocs site deployed to GitHub Pages, serving as the public
face of the project.

## Expected artifacts

- `_quarto.yml` or `mkdocs.yml`
- `index.qmd` — landing page (project blurb + links to paper / slides /
  poster / demo)
- `demo.md` — embedded demo video or hosted link
- `architecture.qmd` — condensed version of `../backend/notes/`
- `results.qmd` — condensed evaluation highlights from
  `../backend/evals/`

## Build

```bash
cd docs
quarto render
```

## Deploy

Configure Pages to serve from the `gh-pages` branch (or `docs/` folder
on `main`) once content is in place.
