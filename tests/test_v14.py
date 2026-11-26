"""AlgoLang v1.4: AlgoOnto™, ontology as code on SQLite, DuckDB and PostgreSQL, with drift detection,
OWL/RDF and JSON-LD export, and a graph view in the CLI and Studio."""
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid

import pytest

import algoonto
from algoc import load_program
from conftest import ROOT

V13, V14 = ROOT / "examples" / "v13", ROOT / "examples" / "v14"
sys.path.insert(0, str(V14))
import make_warehouses  # noqa: E402

QUESTIONS = ["net revenue by region in 2025", "how many orders came through the Online channel",
             "top 3 products by sales", "discount given by category in 2024", "average unit price by category"]


def algo(*args, cwd=None, env=None):
    return subprocess.run([sys.executable, str(ROOT / "algoc.py"), *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd, env=env)


@pytest.fixture
def shop(tmp_path):
    subprocess.run([sys.executable, str(V13 / "make_retail_db.py"), str(tmp_path / "retail.db")], check=True,
                   capture_output=True)
    shutil.copy(V13 / "retail.onto.algo", tmp_path / "retail.onto.algo")
    return tmp_path


def answers(onto):
    out = {}
    for q in QUESTIONS:
        a = algoonto.ask(onto, q)
        assert a["status"] in ("answered", "uncertified"), (q, a.get("reason"))
        out[q] = [[round(x, 2) if isinstance(x, float) else x for x in r] for r in a["rows"]]
    return out


def discovered(spec, tmp_path, name="d.algo"):
    o, notes, rels = algoonto.discover(spec, history=V13 / "query_history.sql")
    f = tmp_path / name
    f.write_text(algoonto.to_source(o, notes, rels), encoding="utf-8")
    return f, algoonto.load_from_program(f)


# ── three engines, one ontology ─────────────────────────────────────────────
needs_duckdb = pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="duckdb not installed")


@needs_duckdb
def test_duckdb_matches_sqlite(shop, tmp_path):
    make_warehouses.to_duckdb(tmp_path / "retail.duckdb", make_warehouses.rows())
    _f, sq = discovered(str(shop / "retail.db"), tmp_path, "s.algo")
    f, dk = discovered(f"duckdb:{tmp_path / 'retail.duckdb'}", tmp_path, "k.algo")
    assert 'from "duckdb:retail.duckdb"' in f.read_text(encoding="utf-8")
    assert set(sq.terms) == set(dk.terms) and sorted(sq.relations) == sorted(dk.relations)
    assert answers(sq) == answers(dk)
    assert algo("check", str(f)).returncode == 0                       # compile-time column check on DuckDB
    assert not [m for s, m in dk.check() if s == "error"]


@needs_duckdb
def test_duckdb_is_read_only(tmp_path):
    make_warehouses.to_duckdb(tmp_path / "r.duckdb", make_warehouses.rows())
    src = algoonto.Source.open(f"duckdb:{tmp_path / 'r.duckdb'}", tmp_path).connect()
    with src, pytest.raises(src.errors):
        src.execute("DELETE FROM orders")


@pytest.fixture(scope="module")
def pg_dsn():
    """A fresh PostgreSQL database for these tests: from ALGO_TEST_PG_DSN (CI starts a postgres service)."""
    base = os.environ.get("ALGO_TEST_PG_DSN")
    if not base or importlib.util.find_spec("psycopg") is None:
        pytest.skip("set ALGO_TEST_PG_DSN (and install psycopg) to test PostgreSQL sources")
    import psycopg
    userinfo = base.split("//")[1].split("@")[0]
    if ":" in userinfo:                    # ontologies say ${PGPASSWORD}: the password comes from the environment
        os.environ.setdefault("PGPASSWORD", userinfo.split(":", 1)[1])
    db = "ontotest_" + uuid.uuid4().hex[:8]
    with psycopg.connect(base, autocommit=True) as con:
        con.execute(f"CREATE DATABASE {db} ENCODING 'UTF8' TEMPLATE template0")
    dsn = base.rsplit("/", 1)[0] + "/" + db
    make_warehouses.to_postgres(dsn, make_warehouses.rows())
    yield dsn
    with psycopg.connect(base, autocommit=True) as con:
        con.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")


def test_postgresql_matches_sqlite(shop, tmp_path, pg_dsn):
    _f, sq = discovered(str(shop / "retail.db"), tmp_path, "s.algo")
    f, pg = discovered(pg_dsn, tmp_path, "p.algo")
    src_line = f.read_text(encoding="utf-8")
    userinfo = pg_dsn.split("//")[1].split("@")[0]
    if ":" in userinfo:                                                # a password in the DSN is never written
        user, password = userinfo.split(":", 1)
        assert f"//{user}:${{PGPASSWORD}}@" in src_line and f":{password}@" not in src_line
    assert set(sq.terms) == set(pg.terms)
    assert answers(sq) == answers(pg)


def test_postgresql_is_read_only_with_a_time_limit(pg_dsn, tmp_path):
    src = algoonto.Source.open(pg_dsn, tmp_path).connect()
    with src:
        with pytest.raises(src.errors):
            src.execute("DELETE FROM orders")
    with algoonto.Source.open(pg_dsn, tmp_path).connect() as src:
        assert src.one("SHOW statement_timeout")[0] in ("5s", "5000ms")
        assert src.one("SHOW transaction_read_only")[0] == "on"


def test_passwords_never_in_source(tmp_path):
    bad = 'ontology X from "postgresql://bob:secret@db/x" { term A "a" { column t.a } }\n'
    ok = 'ontology X from "postgresql://bob:${PGPASSWORD}@db/x" { term A "a" { column t.a } }\n'
    assert "E136" in [d.code for d in load_program(bad, "t.algo", tmp_path)[1]]
    assert not load_program(ok, "t.algo", tmp_path)[1]


# ── drift ───────────────────────────────────────────────────────────────────
def test_no_drift_right_after_a_snapshot(shop):
    o = algoonto.load_from_program(shop / "retail.onto.algo")
    assert algoonto.drift(o, algoonto.snapshot(o)) == []


def test_drift_finds_breaking_changes_new_values_and_stale_certifications(shop):
    o = algoonto.load_from_program(shop / "retail.onto.algo")
    snap = algoonto.snapshot(o)
    con = sqlite3.connect(shop / "retail.db")
    con.execute("ALTER TABLE products RENAME COLUMN category TO product_category")
    con.execute("INSERT INTO customers VALUES (121, 'New Co', 'Central', 'Retail')")
    con.execute("CREATE TABLE returns (id INTEGER PRIMARY KEY, amount REAL)")
    con.execute("UPDATE order_lines SET amount = amount * 1.5")
    con.commit()
    con.close()
    o = algoonto.load_from_program(shop / "retail.onto.algo")
    found = algoonto.drift(o, snap)
    kinds = {(f["severity"], f["kind"]) for f in found}
    assert ("breaking", "column removed") in kinds
    assert any("product_category (renamed?)" in f["message"] for f in found)
    assert any(f["kind"] == "new values" and "Central" in f["message"] for f in found)
    assert any(f["kind"] == "measure moved" and "NetRevenue" in f["terms"] for f in found)
    assert any(f["kind"] == "new table" and "returns" in f["message"] for f in found)
    review = {n for f in found if f["kind"] == "review" for n in f["terms"]}
    assert {"Category", "Region", "NetRevenue"} <= review
    assert not any(f["kind"] == "new values" and "customers.name" in f["message"] for f in found)  # not a category


def test_drift_cli_exit_codes(shop):
    f = shop / "retail.onto.algo"
    assert algo("onto", "drift", str(f)).returncode == 2                 # no snapshot yet
    assert algo("onto", "snapshot", str(f)).returncode == 0
    assert (shop / "retail.onto.snapshot.json").exists()
    assert algo("onto", "drift", str(f)).returncode == 0
    con = sqlite3.connect(shop / "retail.db")
    con.execute("INSERT INTO customers VALUES (121, 'New Co', 'Central', 'Retail')")
    con.commit()
    con.close()
    assert algo("onto", "drift", str(f)).returncode == 0                 # warnings only
    assert algo("onto", "drift", str(f), "--strict").returncode == 1
    out = json.loads(algo("onto", "drift", str(f), "--json").stdout)
    assert any(x["kind"] == "new values" for x in out)


# ── export ──────────────────────────────────────────────────────────────────
def test_export_turtle_and_jsonld_are_the_same_graph(shop):
    rdflib = pytest.importorskip("rdflib")
    from rdflib.compare import isomorphic
    o = algoonto.load_from_program(shop / "retail.onto.algo")
    ttl = rdflib.Graph().parse(data=algoonto.to_turtle(o), format="turtle")
    jl = rdflib.Graph().parse(data=json.dumps(algoonto.to_jsonld(o)), format="json-ld")
    assert len(ttl) == len(algoonto.to_triples(o)) and isomorphic(ttl, jl)
    OWL, SKOS = rdflib.OWL, rdflib.namespace.SKOS
    classes = {str(x).split("#")[1] for x in ttl.subjects(rdflib.RDF.type, OWL.Class)}
    assert classes == {"Customer", "Order", "OrderLine", "Product"}
    assert len(list(ttl.subjects(rdflib.RDF.type, OWL.ObjectProperty))) == 3
    rev = rdflib.URIRef("urn:algolang:onto:Retail#NetRevenue")
    assert (rev, SKOS.altLabel, rdflib.Literal("sales")) in ttl
    algo_ns = rdflib.Namespace(algoonto.ALGO_NS)
    assert str(ttl.value(rev, algo_ns.measure)) == "SUM(order_lines.amount)"
    assert str(ttl.value(rdflib.URIRef("urn:algolang:onto:Retail#DiscountGiven"), algo_ns.status)) == "proposed"


def test_export_cli(shop):
    out = shop / "r.ttl"
    r = algo("onto", "export", str(shop / "retail.onto.algo"), "-o", str(out))
    assert r.returncode == 0 and "owl:Ontology" in out.read_text(encoding="utf-8")
    j = algo("onto", "export", str(shop / "retail.onto.algo"), "--format", "jsonld")
    assert "@graph" in json.loads(j.stdout)


# ── graph view ──────────────────────────────────────────────────────────────
def test_graph_svg_shows_entities_joins_and_certification(shop):
    o = algoonto.load_from_program(shop / "retail.onto.algo")
    svg = algoonto.graph_svg(o)
    assert svg.startswith("<svg") and svg.count('marker-end="url(#arr)"') == 3
    for t in ("OrderLine", "Order", "Customer", "Product", "16/17 terms certified"):
        assert t in svg
    page = shop / "g.html"
    assert algo("onto", "graph", str(shop / "retail.onto.algo"), "--html", str(page)).returncode == 0
    assert "AlgoOnto™" in page.read_text(encoding="utf-8")


def test_studio_ontology_page(shop, monkeypatch):
    import algostudio
    monkeypatch.setattr(algostudio, "WORKSPACE", shop)
    html = algostudio.ontology_page()
    assert "AlgoOnto™" in html and "<svg" in html and "Retail" in html


def test_algo_onto_alias(shop):
    a = algo("onto", "terms", str(shop / "retail.onto.algo"))
    b = algo("ontology", "terms", str(shop / "retail.onto.algo"))
    assert a.returncode == 0 and a.stdout == b.stdout and "NetRevenue" in a.stdout


# ── the shipped v1.4 examples ───────────────────────────────────────────────
def test_example_ontologies_compile_and_are_certified():
    for f, src in (("retail_duckdb.onto.algo", 'from "duckdb:retail.duckdb"'),
                   ("retail_postgres.onto.algo", 'from "postgresql://analyst:${PGPASSWORD}@localhost:5432/retail"')):
        text = (V14 / f).read_text(encoding="utf-8")
        assert src in text and "secret" not in text
        prog, diags = load_program(text, f, V14)
        assert not diags
        (o,) = prog.ontologies.values()
        assert len(o["terms"]) == 17 and sum(1 for t in o["terms"].values() if t.get("certified")) == 16


@needs_duckdb
def test_warehouse_analyst_example(tmp_path):
    for f in ("warehouse_analyst.algo", "retail_duckdb.onto.algo"):
        shutil.copy(V14 / f, tmp_path / f)
    make_warehouses.to_duckdb(tmp_path / "retail.duckdb", make_warehouses.rows())
    r = algo("eval", str(tmp_path / "warehouse_analyst.algo"), cwd=tmp_path)
    assert r.returncode == 0 and "2/2 cases pass" in r.stdout
    q = "question=top 3 products by sales in 2025"
    a = algo("run", str(tmp_path / "warehouse_analyst.algo"), "--arg", q, cwd=tmp_path)
    b = algo("run", str(tmp_path / "warehouse_analyst.algo"), "--engine", "vm", "--arg", q, cwd=tmp_path)
    emitted = lambda out: out.split("■ emitted:")[1].split("■")[0]
    assert "879,124.67" in emitted(a.stdout) and emitted(a.stdout) == emitted(b.stdout)


def test_warehouse_analyst_refuses_without_its_data(tmp_path):
    for f in ("warehouse_analyst.algo", "retail_duckdb.onto.algo"):
        shutil.copy(V14 / f, tmp_path / f)
    r = algo("run", str(tmp_path / "warehouse_analyst.algo"), "--arg", "question=net revenue by region", cwd=tmp_path)
    assert r.returncode == 0 and "cannot be answered from the certified data definitions" in r.stdout


def test_committed_baseline_shows_no_drift():
    r = algo("onto", "drift", str(V13 / "retail.onto.algo"))
    assert r.returncode == 0 and "no drift" in r.stdout


def test_drift_demo_reports_the_rename():
    r = subprocess.run([sys.executable, str(V14 / "drift_demo.py")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1 and "product_category (renamed?)" in r.stdout and "Central" in r.stdout
    assert sqlite3.connect(V13 / "retail.db").execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 120


def test_committed_exports_are_current():
    o = algoonto.load_from_program(V13 / "retail.onto.algo")
    strip = lambda t: "\n".join(x for x in t.splitlines() if not x.startswith("# AlgoOnto™ export"))  # noqa: E731
    assert strip((V14 / "exports" / "retail.ttl").read_text(encoding="utf-8")) == strip(algoonto.to_turtle(o))
    assert json.loads((V14 / "exports" / "retail.jsonld").read_text(encoding="utf-8")) == algoonto.to_jsonld(o)
    assert "<svg" in (V14 / "exports" / "retail-graph.html").read_text(encoding="utf-8")
