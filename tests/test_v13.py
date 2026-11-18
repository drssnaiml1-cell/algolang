"""AlgoLang v1.3: ontology as code (discover, certify, ground, answer, validate, serve)."""
import json
import shutil
import subprocess
import sys

import pytest

import algolang as al
import algoonto
from algoc import load_program
from conftest import ROOT

V13 = ROOT / "examples" / "v13"


@pytest.fixture
def shop(tmp_path):
    """A fresh copy of the example database and ontology."""
    subprocess.run([sys.executable, str(V13 / "make_retail_db.py"), str(tmp_path / "retail.db")], check=True,
                   capture_output=True)
    shutil.copy(V13 / "retail.onto.algo", tmp_path / "retail.onto.algo")
    shutil.copy(V13 / "query_history.sql", tmp_path / "query_history.sql")
    return tmp_path


def onto(shop):
    return algoonto.load_from_program(shop / "retail.onto.algo")


def algo(*args, cwd=None):
    return subprocess.run([sys.executable, str(ROOT / "algoc.py"), *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd)


def codes(src, base):
    prog, diags = load_program(src, "t.algo", base)
    return [d.code for d in diags]


# ── discovery ────────────────────────────────────────────────────────────────
def test_discover_profiles_schema_joins_and_history(shop):
    o, notes, rels = algoonto.discover(shop / "retail.db", history=shop / "query_history.sql")
    assert {"Customer", "Order", "Product", "Region", "Channel", "NetRevenue", "DiscountGiven"} <= set(o.terms)
    kinds = {(a, b): why for a, b, why in rels}
    assert kinds[("orders.customer_id", "customers.id")] == "declared foreign key"
    assert kinds[("order_lines.product_id", "products.id")].startswith("inferred")
    assert o.terms["NetRevenue"]["measure"] == "SUM(order_lines.amount)"          # renamed from query history
    assert o.terms["DiscountGiven"]["measure"].startswith("SUM(order_lines.quantity * products.unit_price)")
    assert o.terms["Discount"]["measure"] == "AVG(order_lines.discount)"           # a 0..1 ratio is averaged
    assert not any(t.get("certified") for t in o.terms.values())


def test_discovered_source_compiles_and_matches_the_data(shop):
    o, notes, rels = algoonto.discover(shop / "retail.db", history=shop / "query_history.sql")
    (shop / "d.algo").write_text(algoonto.to_source(o, notes, rels), encoding="utf-8")
    assert algo("check", str(shop / "d.algo")).returncode == 0
    problems = algoonto.load_from_program(shop / "d.algo").check()
    assert not [m for sev, m in problems if sev == "error"]


def test_certify_writes_the_review_into_the_source(shop):
    f = shop / "retail.onto.algo"
    algoonto.certify_source(f, "DiscountGiven", "cfo-office", "2026-11-18")
    assert 'certified "cfo-office" on "2026-11-18"' in f.read_text(encoding="utf-8")
    assert onto(shop).certified("DiscountGiven")


# ── compile-time checks (E136) ───────────────────────────────────────────────
@pytest.mark.parametrize("body", [
    'term A "x" { }',                                                   # no column
    'term A "x" { column orders }',                                     # not table.column
    'term A "x" { column orders.id  measure "orders.id" }',             # measure must aggregate
    'term A "x" { column orders.id  measure "SUM(orders.id); DROP TABLE orders" }',
    'term A "x" { column orders.id }  term B "y" { synonyms "a"  column orders.channel }',   # one word, two terms
    'term A "x" { column orders.nope }',                                # not in the database
    'relation orders.customer_id -> people.id',                         # not in the database
])
def test_ontology_errors_e136(shop, body):
    assert "E136" in codes(f'ontology T from "retail.db" {{ {body} }}\n', shop)


def test_grounded_in_unknown_ontology(shop):
    src = 'agent A(q: text) -> text { goal "{q}"  grounded in Nope }\nflow main(q: text) { emit A(q) }\n'
    assert "E136" in codes(src, shop)


def test_high_risk_programs_need_every_term_certified(shop):
    prog = ('risk high "credit decisions"\ndisclose "AI."\nuse "retail.onto.algo"\n'
            'agent A(q: text) -> text { goal "{q}"  grounded in Retail  policy { require human for always  '
            'explain  redact pii } }\nflow main(q: text) { emit A(q) }\n')
    assert "E136" in codes(prog, shop)                                  # DiscountGiven is not certified
    algoonto.certify_source(shop / "retail.onto.algo", "DiscountGiven", "cfo-office")
    assert "E136" not in codes(prog, shop)


# ── answering ────────────────────────────────────────────────────────────────
def test_answers_match_hand_written_sql(shop):
    import sqlite3
    o = onto(shop)
    con = sqlite3.connect(shop / "retail.db")
    a = algoonto.ask(o, "How many orders came through the Online channel?")
    assert a["status"] == "answered" and a["rows"][0][0] == con.execute(
        "SELECT COUNT(*) FROM orders WHERE channel='Online'").fetchone()[0]
    a = algoonto.ask(o, "net revenue by region in 2025")
    want = dict(con.execute("SELECT c.region, SUM(l.amount) FROM order_lines l JOIN orders o ON l.order_id=o.id "
                            "JOIN customers c ON o.customer_id=c.id WHERE o.order_date LIKE '2025%' GROUP BY c.region"))
    assert {r[0]: round(r[1], 2) for r in a["rows"]} == {k: round(v, 2) for k, v in want.items()}
    assert a["certified"] == a["terms"] and "JOIN customers ON orders.customer_id = customers.id" in a["sql"]


def test_top_n_and_lowest(shop):
    o = onto(shop)
    a = algoonto.ask(o, "top 3 products by sales")
    assert len(a["rows"]) == 3 and a["columns"] == ["Product", "NetRevenue"]
    assert a["rows"][0][1] >= a["rows"][1][1] >= a["rows"][2][1]
    b = algoonto.ask(o, "lowest region by turnover")
    assert len(b["rows"]) == 1


@pytest.mark.parametrize("q", ["headcount by department", "revenue by department", "what is the weather in Delhi"])
def test_unanswerable_is_never_guessed(shop, q):
    a = algoonto.ask(onto(shop), q)
    assert a["status"] == "unanswerable" and a["reason"]


def test_uncertified_definitions_are_flagged(shop):
    a = algoonto.ask(onto(shop), "discount given in 2025")
    assert a["status"] == "uncertified" and a["uncertified"] == ["DiscountGiven"]
    assert "UNCERTIFIED" in algoonto.render_answer(a)


@pytest.mark.parametrize("sql,problem", [
    ("SELECT SUM(order_lines.amount*2) FROM order_lines", "not a defined measure"),
    ("SELECT SUM(order_lines.amount) FROM order_lines JOIN customers ON order_lines.order_id = customers.id",
     "not a declared relation"),
    ("SELECT * FROM salaries", "not part of ontology"),
    ("DELETE FROM orders", "only SELECT"),
    ("SELECT SUM(order_lines.amount) FROM order_lines; DROP TABLE orders", "more than one statement"),
    ("SELECT COUNT(DISTINCT orders.id) FROM orders WHERE orders.channel = 'Telepathy'", "no row has"),
])
def test_validator_rejects(shop, sql, problem):
    v = algoonto.validate_sql(onto(shop), sql)
    assert not v["ok"] and any(problem in p for p in v["problems"])


def test_validator_accepts_certified_sql_and_flags_uncertified(shop):
    o = onto(shop)
    ok = algoonto.validate_sql(o, "SELECT customers.region, SUM(order_lines.amount) FROM order_lines JOIN orders ON "
                                  "order_lines.order_id = orders.id JOIN customers ON orders.customer_id = customers.id "
                                  "GROUP BY customers.region")
    assert ok["ok"] and ok["terms"] == ["NetRevenue", "Region"]
    unc = algoonto.validate_sql(o, "SELECT SUM( order_lines.quantity * products.unit_price ) - SUM(order_lines.amount) "
                                   "FROM order_lines JOIN products ON order_lines.product_id = products.id")
    assert not unc["ok"] and unc["uncertified"] == ["DiscountGiven"] and not unc["problems"]


def test_queries_are_read_only(shop):
    o = onto(shop)
    con = o.connect()
    with pytest.raises(Exception):
        con.execute("DELETE FROM orders")


# ── grounded agents ──────────────────────────────────────────────────────────
def test_grounded_agent_answers_with_lineage_in_the_audit(shop):
    shutil.copy(V13 / "sales_analyst.algo", shop / "sales_analyst.algo")
    prog = al.load(str(shop / "sales_analyst.algo"))
    res = prog.run(question="net revenue by region in 2025", audit_dir=str(shop / "runs"))
    assert res.ok and "North" in str(res.values[0])
    rec = [json.loads(x) for x in open(res.audit_path, encoding="utf-8")][-1]
    g = rec["grounding"]
    assert rec["policy"]["grounded"] == "Retail" and g["ontology"] == "Retail"
    assert g["answers"][0]["status"] == "answered" and "NetRevenue" in g["answers"][0]["certified"]


def test_grounded_program_runs_identically_on_the_algovm(shop):
    shutil.copy(V13 / "sales_analyst.algo", shop / "sales_analyst.algo")
    q = "question=top 3 products by sales in 2025"
    a = algo("run", str(shop / "sales_analyst.algo"), "--arg", q, cwd=shop)
    b = algo("run", str(shop / "sales_analyst.algo"), "--engine", "vm", "--arg", q, cwd=shop)
    emitted = lambda out: out.split("■ emitted:")[1].split("■")[0]
    assert a.returncode == 0 and emitted(a.stdout) == emitted(b.stdout) and "NetRevenue" in emitted(a.stdout)


def test_signed_ir_carries_the_certifications(shop):
    import algoir
    prog, _ = load_program((V13 / "sales_analyst.algo").read_text(encoding="utf-8"), "sales_analyst.algo", shop)
    doc = algoir.to_ir(prog, "sales_analyst")
    assert doc["ontologies"]["Retail"]["terms"]["NetRevenue"]["certified"] == "finance-data-team"


# ── command line and MCP ─────────────────────────────────────────────────────
def test_cli_round_trip(shop):
    d = algo("ontology", "discover", str(shop / "retail.db"), "-o", str(shop / "new.algo"))
    assert d.returncode == 0 and "terms" in d.stdout
    assert algo("ontology", "certify", str(shop / "new.algo"), "Region", "--by", "ops").returncode == 0
    assert algo("ontology", "check", str(shop / "new.algo")).returncode == 0
    ask = algo("ontology", "ask", str(shop / "retail.onto.algo"), "orders by channel", "--json")
    assert ask.returncode == 0 and json.loads(ask.stdout)["status"] == "answered"
    assert algo("ontology", "ask", str(shop / "retail.onto.algo"), "headcount by department").returncode == 1
    assert algo("ontology", "validate", str(shop / "retail.onto.algo"), "SELECT * FROM salaries").returncode == 1


def test_mcp_exposes_read_only_ontology_tools(shop):
    import algoserve
    srv = algoserve.FlowServer([str(shop / "retail.onto.algo")])
    names = set(srv.tools)
    assert {"retail_search_terms", "retail_get_term", "retail_check_answerable", "retail_ask_question",
            "retail_validate_sql"} <= names
    out = srv.call("retail_ask_question", {"question": "net revenue by channel in 2025"})
    assert not out["isError"] and "NetRevenue" in out["content"][0]["text"]
    assert srv.call("retail_ask_question", {"question": "headcount by department"})["isError"]
