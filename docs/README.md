# AlgoLang Documentation (LaTeX source)

*The AlgoLang Programming Language — Official Documentation, v0.1*
Dr. S. Satyanarayana, Ph.D., PDF (AI) · AlgoProfessor AI R&D Solutions

- `AlgoLang_Documentation_v0.1.pdf` — compiled book (72 pages)
- `algolang-docs.tex` — main file
- `algolang-docs.sty` — navy & gold house style
- `chapters/` — one file per chapter and appendix

## Build

```
latexmk -xelatex algolang-docs.tex
```

or run `xelatex algolang-docs.tex` twice. On Overleaf, set **Compiler = XeLaTeX**.
Fonts: TeX Gyre Pagella, Inter and DejaVu Sans Mono; if Inter is missing, TeX Gyre Heros is used automatically.
