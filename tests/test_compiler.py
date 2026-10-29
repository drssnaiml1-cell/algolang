"""Compiler: grammar, checks and code generation."""
import re

import pytest

from algoc import CompileError, compile_source
from conftest import SIMPLE


def codes(src, name="t.algo"):
    with pytest.raises(CompileError) as e:
        compile_source(src, name)
    return {d.code for d in e.value.diags}


def test_simple_program_compiles():
    code, prog = compile_source(SIMPLE, "simple.algo")
    assert "def flow_main" in code
    assert list(prog.agents) == ["Echo"]


@pytest.mark.parametrize("path", ["examples/research_brief.algo", "examples/paper_review.algo"])
def test_examples_compile(root, path):
    f = root / path
    compile_source(f.read_text(encoding="utf-8"), f.name, f.parent)


def test_every_example_and_app_compiles(root):
    files = [f for f in (root / "examples").rglob("*.algo")
             if "build" not in f.parts and f.name != "bad_example.algo" and re.search(r"flow\s+main", f.read_text())]
    assert len(files) >= 10
    for f in files:
        compile_source(f.read_text(encoding="utf-8"), f.name, f.parent)


def test_bad_example_reports_documented_errors(root):
    f = root / "examples" / "bad_example.algo"
    got = codes(f.read_text(encoding="utf-8"), f.name)
    assert {"E101", "E102", "E103", "E104", "E106", "E108", "E109", "E110"} <= got


@pytest.mark.parametrize("src,code", [
    ("agent A(x: text) -> text { role \"r\" goal \"g {x}\" }\nflow main(x: text) { y = len(x) emit y }", "E101"),
    ("agent A(x: text) -> text { role \"r\" goal \"g {x}\" }\nflow main(x: text) { y = A(x, x) emit y }", "E102"),
    ("agent A(x: text) -> text { role \"r\" goal \"g {x}\" }\nflow main(x: text) { y = A(z) emit y }", "E103"),
    ("agent A(x: text) -> text { role \"r\" goal \"g {x}\" uses web.search }\nflow main(x: text) { y = A(x) emit y }", "E104"),
    ("agent A(x: text) -> text { role \"r\" goal \"g {zz}\" }\nflow main(x: text) { y = A(x) emit y }", "E109"),
    ("agent A(x: text) -> text { role \"r\" goal \"g {x}\" }", "E111"),
    ("agent A(x: text) -> text { role \"r\" }\nflow main(x: text) { y = A(x) emit y }", "E112"),
    ("agent A(caste: text) -> text { role \"r\" goal \"g {caste}\" policy { forbid caste } }\n"
     "flow main(x: text) { y = A(x) emit y }", "E108"),
    ("agent A(x: text) -> text { role \"r\" goal \"g {x}\"\n", "E100"),
])
def test_each_error_code(src, code):
    assert code in codes(src)


def test_diagnostics_have_line_numbers():
    with pytest.raises(CompileError) as e:
        compile_source("\n\nagent A(x: text) -> text { role \"r\" }\nflow main(x: text) { y = A(x) emit y }", "t.algo")
    assert e.value.diags[0].line == 3


def test_generated_python_is_valid(root):
    f = root / "examples" / "paper_review.algo"
    code, _ = compile_source(f.read_text(encoding="utf-8"), f.name, f.parent)
    compile(code, "<gen>", "exec")
