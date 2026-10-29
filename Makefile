# AlgoLang developer shortcuts. Windows users: run the commands shown after each target.
PY ?= python

.PHONY: install check lint test fast algo-lint build packs docs clean

install:        ## pip install -e ".[dev,live]"
	$(PY) -m pip install -e ".[dev,live]"

check: lint test algo-lint   ## everything CI runs

lint:           ## ruff check .
	ruff check .

test:           ## pytest
	$(PY) -m pytest

fast:           ## pytest -m "not slow"
	$(PY) -m pytest -m "not slow"

algo-lint:      ## python algoc.py dev lint examples packs
	$(PY) algoc.py dev lint examples packs

build:          ## python -m build
	$(PY) -m build

packs:          ## regenerate the 120 domain packs + catalog
	$(PY) tools/make_packs.py

docs:           ## build the PDF manual (needs XeLaTeX)
	cd docs && xelatex -interaction=nonstopmode algolang-docs.tex && xelatex -interaction=nonstopmode algolang-docs.tex

clean:
	rm -rf dist build .pytest_cache .ruff_cache **/__pycache__ runs examples/build examples/runs
