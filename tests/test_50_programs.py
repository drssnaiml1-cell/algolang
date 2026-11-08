"""Every program from 'AlgoLang: 50 Sample Programs' (docs/AlgoLang_50_Sample_Programs.pdf) compiles and runs."""
import json

import pytest

import algolang as al
from conftest import ROOT

DIR = ROOT / "examples" / "50-programs"
INPUTS = json.loads((DIR / "inputs.json").read_text(encoding="utf-8"))


def test_there_are_fifty():
    assert len(INPUTS) == 50 and len(list(DIR.glob("P*.algo"))) == 50
    assert (ROOT / "docs" / "AlgoLang_50_Sample_Programs.pdf").exists()


@pytest.mark.parametrize("name", sorted(INPUTS))
def test_program_runs_with_its_documented_input(name):
    r = al.load(DIR / name).run(**INPUTS[name])
    assert r.status == "ok", r.problem
    assert r.values and r.stats["calls"] >= 1
