"""v0.2 modules: use "file" / use pack, aliases, file-level policy, cycles."""
import pytest

from algoc import CompileError, compile_source
from conftest import write

LIB = 'agent Helper(x: text) -> text {\n role "h"\n goal "help with {x}"\n}\n'


def test_use_file_with_alias(project):
    write(project / "lib" / "helpers.algo", LIB)
    main = write(project / "main.algo", 'use "lib/helpers.algo" as h\nflow main(x: text) { y = h.Helper(x) emit y }\n')
    code, prog = compile_source(main.read_text(), "main.algo", project)
    assert "h.Helper" in prog.agents
    assert "h__Helper" in code


def test_use_pack(project):
    src = 'use pack insurance.claims_triage as claims\nflow main(c: text) { a = claims.Intake(c) emit a }\n'
    _, prog = compile_source(src, "m.algo", project)
    assert "claims.Intake" in prog.agents


def test_unknown_pack_is_an_error(project):
    with pytest.raises(CompileError):
        compile_source('use pack nowhere.nothing as n\nflow main(c: text) { a = n.X(c) emit a }\n', "m.algo", project)


def test_circular_use_is_rejected(project):
    write(project / "a.algo", 'use "b.algo" as b\n' + LIB)
    write(project / "b.algo", 'use "a.algo" as a\n' + LIB.replace("Helper", "Other"))
    with pytest.raises(CompileError) as e:
        compile_source('use "a.algo" as a\nflow main(x: text) { y = a.Helper(x) emit y }\n', "main.algo", project)
    assert "circular" in str(e.value).lower() or any("circular" in d.msg.lower() for d in e.value.diags)


def test_file_policy_applies_to_every_agent(project):
    src = ('policy {\n budget tokens 1234\n forbid caste\n}\n' + LIB +
           'flow main(x: text) { y = Helper(x) emit y }\n')
    _, prog = compile_source(src, "m.algo", project)
    pol = prog.agents["Helper"].policy
    assert pol.get("budget_tokens") == 1234
    assert "caste" in pol.get("forbid", [])
