# AlgoLang presentation (LaTeX Beamer)

*AlgoLang — An Agent-Native Programming Language for Building AI Systems*
Dr. S. Satyanarayana, Ph.D., PDF (AI) · AlgoProfessor AI R&D Solutions

- `AlgoLang_Presentation.pdf` — compiled deck (57 slides, 16:9)
- `algolang-slides.tex` — slide source
- `beamerthemeAlgoLang.sty` — colourful navy & gold theme (one accent colour per part)
- `images/` — real screenshots of AlgoLang Studio and the notebook
- Application slides print their code directly from `../examples/apps/*.algo`, so keep the folder layout.

## Build

```
latexmk -xelatex algolang-slides.tex
```

On Overleaf, upload the whole `algolang` folder (or at least `slides/` and `examples/apps/`) and set **Compiler = XeLaTeX**.
