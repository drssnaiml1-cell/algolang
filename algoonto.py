"""algoonto: AlgoOnto™, ontology as code: a governed context layer for data agents (v1.3; v1.4 AlgoOnto™).

Inspired by NVIDIA's open-source Auto Ontology (github.com/NVIDIA/auto-ontology), which builds a context layer
so that agents know where enterprise data lives, what it means, and how to compute it. AlgoLang takes the same
idea one step further: the ontology is source code. It is declared in the language, checked by the compiler,
reviewed in pull requests, certified by name in the source, and enforced at run time.

    ontology Retail from "retail.db" {                       // SQLite file, "duckdb:file.duckdb" or
        term Revenue "Net sales value of order lines" {      // "postgresql://host/db" (v1.4)
            synonyms "sales", "turnover"
            column order_lines.amount
            measure "SUM(order_lines.amount)"
            certified "finance-team" on "2026-11-18"
        }
        term Region "Sales region of the customer" { column customers.region }
        relation orders.customer_id -> customers.id
    }

    agent Analyst(q: text) -> text {
        goal "Answer {q} from the company's data"
        grounded in Retail                  // certified definitions only; lineage in the audit log
    }

The AlgoOnto™ life cycle (`algo onto …`, also `algo ontology …`), offline and deterministic:

    discover   algo onto discover retail.db           profile the schema and propose terms, columns, joins and
                                                      measures (from data and query history) as AlgoLang source
    certify    algo onto certify file.algo Revenue --by finance-team
                                                      a person signs off a definition, in the source
    answer     algo onto ask file.algo "revenue by region in 2025"
                                                      plan SQL from certified measures and declared joins,
                                                      validate it, run it read-only, return answer + lineage
    watch      algo onto snapshot / drift (v1.4)      detect schema and data drift that invalidates definitions
    share      algo onto export --format ttl|jsonld   OWL/RDF and JSON-LD for other tools (v1.4)
               algo onto graph --html (v1.4)          a picture of entities, joins and certification

Questions the definitions cannot support are reported as unanswerable, never guessed. Any SQL, from a person
or a model, can be checked against the ontology with `algo onto validate`.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

GOLD, DIM, BOLD, GREEN, RED, END = "\033[33m", "\033[2m", "\033[1m", "\033[32m", "\033[31m", "\033[0m"
if not __import__("sys").stdout.isatty() or __import__("os").environ.get("NO_COLOR"):
    GOLD = DIM = BOLD = GREEN = RED = END = ""

REGISTRY: dict = {}            # name -> Ontology, filled by compiled programs (rt.register_ontology)
MAX_ROWS = 50
QUERY_SECONDS = 5.0

# business vocabulary used when proposing synonyms (discovery) and when matching questions (retrieval)
SYNONYMS = {
    "amount": ["value", "total"], "revenue": ["sales", "turnover", "income"], "sales": ["revenue", "turnover"],
    "customer": ["client", "buyer", "account"], "region": ["area", "zone", "territory"],
    "product": ["item", "sku", "article"], "category": ["segment", "group", "type"],
    "quantity": ["units", "qty", "volume"], "qty": ["quantity", "units"], "price": ["rate", "unit price"],
    "date": ["day", "when"], "order": ["purchase", "transaction"], "employee": ["staff", "worker"],
    "city": ["town", "location"], "supplier": ["vendor"], "cost": ["expense", "spend"], "discount": ["rebate"],
    "name": ["title"], "country": ["nation"], "channel": ["route", "medium"], "margin": ["profit"],
}
STOP = set("a an the of in on for by per each to from with and or is are was were what which who how much many "
           "me show give list tell our we my all total number count did does do this that last than over across "
           "between top highest lowest most least largest smallest best worst".split())
SQL_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|"
                           r"grant|revoke|truncate|merge|call|exec|load_extension)\b", re.I)


class OntologyError(Exception):
    pass


# ── data sources (v1.4): SQLite, DuckDB, PostgreSQL ────────────────────────────────────────────────────────
class Source:
    """One read-only connection to a data source. Every engine is opened read-only with a time limit, so neither
    a planned query nor any validated SQL can change data or run for ever."""
    kind = "sqlite"
    errors: tuple = (sqlite3.Error,)

    def __init__(self, spec, base):
        self.spec, self.base = spec, Path(base)
        self.con = None

    # opening ---------------------------------------------------------------------------------------------------
    @staticmethod
    def open(spec, base):
        """`retail.db` / `x.sqlite` (SQLite file), `duckdb:x.duckdb` or `x.duckdb` (DuckDB file),
        `postgresql://host/db` (PostgreSQL; credentials from the environment, or ${VAR} references)."""
        expanded = os.path.expandvars(spec or "")
        if re.match(r"(?i)^postgres(ql)?://", expanded):
            return PostgresSource(expanded, base)
        if expanded.lower().startswith("duckdb:") or expanded.lower().endswith(".duckdb"):
            return DuckDBSource(expanded.split(":", 1)[1] if expanded.lower().startswith("duckdb:") else expanded, base)
        return SQLiteSource(expanded, base)

    @property
    def path(self):
        p = Path(self.spec)
        return p if p.is_absolute() else self.base / p

    def exists(self):
        return self.path.exists()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.con is not None:
            try:
                self.con.close()
            finally:
                self.con = None

    # querying (placeholders are `?` everywhere; adapters translate) --------------------------------------------
    def execute(self, sql, params=()):
        cur = self.con.cursor()
        cur.execute(sql, tuple(params))
        return cur

    def rows(self, sql, params=(), limit=None):
        cur = self.execute(sql, params)
        return cur.fetchmany(limit) if limit else cur.fetchall()

    def one(self, sql, params=()):
        return self.execute(sql, params).fetchone()

    def explain(self, sql, params=()):
        self.execute("EXPLAIN " + sql, params).fetchall()

    def year_expr(self, col):
        return f"strftime('%Y', {col})"

    @staticmethod
    def is_text(typ):
        t = (typ or "").upper()
        return any(k in t for k in ("CHAR", "TEXT", "CLOB", "STRING")) or t == ""

    @staticmethod
    def is_number(typ):
        return any(k in (typ or "").upper() for k in ("INT", "REAL", "NUM", "DEC", "FLOA", "DOUB"))


class SQLiteSource(Source):
    kind = "sqlite"

    def connect(self):
        if not self.exists():
            raise OntologyError(f"data source {self.spec!r} not found")
        self.con = sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True, timeout=QUERY_SECONDS)
        start = time.monotonic()
        self.con.set_progress_handler(lambda: 1 if time.monotonic() - start > QUERY_SECONDS else 0, 10_000)
        return self

    def tables(self):
        return [r[0] for r in self.rows("SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                                        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    def columns(self, t):
        return [(c[1], (c[2] or "").upper(), bool(c[5])) for c in self.rows(f'PRAGMA table_info("{t}")')]

    def foreign_keys(self, t):
        return [(fk[3], fk[2], fk[4] or "id") for fk in self.rows(f'PRAGMA foreign_key_list("{t}")')]


class DuckDBSource(Source):
    kind = "duckdb"

    def connect(self):
        try:
            import duckdb
        except ImportError as e:
            raise OntologyError("DuckDB sources need the duckdb package: pip install duckdb") from e
        if not self.exists():
            raise OntologyError(f"data source {self.spec!r} not found")
        self.errors = (duckdb.Error,)
        self.con = duckdb.connect(str(self.path), read_only=True)
        return self

    def execute(self, sql, params=()):
        timer = threading.Timer(QUERY_SECONDS, self.con.interrupt)
        timer.start()
        try:
            return self.con.execute(sql, list(params))
        finally:
            timer.cancel()

    def tables(self):
        return [r[0] for r in self.rows("SELECT table_name FROM information_schema.tables WHERE table_schema = "
                                        "'main' ORDER BY table_name")]

    def columns(self, t):
        pks = {r[0] for r in self.rows("SELECT unnest(constraint_column_names) FROM duckdb_constraints() WHERE "
                                       "table_name = ? AND constraint_type = 'PRIMARY KEY'", (t,))}
        return [(r[0], r[1].upper(), r[0] in pks) for r in
                self.rows("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ? "
                          "ORDER BY ordinal_position", (t,))]

    def foreign_keys(self, t):
        out = []
        for cols, ref_t, ref_cols in self.rows(
                "SELECT constraint_column_names, referenced_table, referenced_column_names FROM duckdb_constraints() "
                "WHERE table_name = ? AND constraint_type = 'FOREIGN KEY'", (t,)):
            if cols and ref_t:
                out.append((cols[0], ref_t, (ref_cols or ["id"])[0]))
        return out

    def year_expr(self, col):
        return f"strftime(CAST({col} AS DATE), '%Y')"


class PostgresSource(Source):
    kind = "postgresql"

    @property
    def path(self):
        return Path(re.sub(r"//[^@/]*@", "//", self.spec))          # never show credentials

    def exists(self):
        return True

    def connect(self):
        try:
            import psycopg
        except ImportError as e:
            raise OntologyError('PostgreSQL sources need psycopg: pip install "psycopg[binary]"') from e
        self.errors = (psycopg.Error,)
        try:
            self.con = psycopg.connect(self.spec, connect_timeout=int(QUERY_SECONDS), autocommit=False)
        except psycopg.Error as e:
            raise OntologyError(f"cannot connect to {self.path}: {str(e).strip().splitlines()[0]}") from e
        self.con.read_only = True                                     # a read-only transaction: no writes possible
        self.con.execute("SET client_encoding TO 'UTF8'")            # text comes back as text on any server
        self.con.execute(f"SET statement_timeout = {int(QUERY_SECONDS * 1000)}")
        return self

    def close(self):
        if self.con is not None:
            try:
                self.con.rollback()
            except Exception:  # noqa
                pass
        super().close()

    def execute(self, sql, params=()):
        if params:                                                    # `?` → `%s` (and a literal % → %%)
            out, q = [], False
            for ch in sql:
                if ch == "'":
                    q = not q
                out.append("%%" if ch == "%" else ("%s" if ch == "?" and not q else ch))
            sql = "".join(out)
        cur = self.con.cursor()
        cur.execute(sql, tuple(params) if params else None)
        return cur

    def tables(self):
        return [r[0] for r in self.rows("SELECT table_name::text FROM information_schema.tables WHERE table_schema = "
                                        "current_schema() ORDER BY 1")]

    def columns(self, t):
        pks = {r[0] for r in self.rows(
            "SELECT a.attname::text FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = "
            "ANY(i.indkey) WHERE i.indrelid = ?::regclass AND i.indisprimary", (t,))}
        return [(r[0], r[1].upper(), r[0] in pks) for r in
                self.rows("SELECT column_name::text, data_type::text FROM information_schema.columns WHERE table_schema = "
                          "current_schema() AND table_name = ? ORDER BY ordinal_position", (t,))]

    def foreign_keys(self, t):
        return [tuple(r) for r in self.rows(
            "SELECT kcu.column_name::text, ccu.table_name::text, ccu.column_name::text FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name "
            "JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = ?", (t,))]

    def year_expr(self, col):
        return f"to_char(CAST({col} AS date), 'YYYY')"


# ── the model ────────────────────────────────────────────────────────────────────────────────────────────────
def _words(s):
    return [w for w in re.findall(r"[a-z0-9]+", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(s)).lower())]


def _stem(w):
    for suf in ("ies", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


class Ontology:
    """Terms (business concepts mapped to columns, optionally with a certified SQL measure), relations (how
    tables join) and the source they describe."""

    def __init__(self, name, source=None, terms=None, relations=None, base=None):
        self.name, self.source = name, source
        self.terms = terms or {}             # name -> {description, synonyms, columns, measure, certified, on, line}
        self.relations = relations or []     # [(table.col, table.col)]
        self.base = Path(base) if base else Path.cwd()
        self._values = None

    # serialisation (compiled programs and AlgoIR carry the ontology as JSON)
    def to_dict(self):
        return dict(name=self.name, source=self.source, terms=self.terms, relations=[list(r) for r in self.relations])

    @classmethod
    def from_dict(cls, d, base=None):
        return cls(d["name"], d.get("source"), dict(d.get("terms") or {}), [tuple(r) for r in d.get("relations") or []],
                   base)

    @property
    def db_path(self):
        if not self.source:
            return None
        return Source.open(self.source, self.base).path

    def connect(self):
        """A read-only Source for this ontology's data (use as a context manager)."""
        if not self.source:
            raise OntologyError(f"ontology {self.name} has no data source (ontology {self.name} from \"…\")")
        src = Source.open(self.source, self.base)
        try:
            return src.connect()
        except OntologyError as e:
            raise OntologyError(f"ontology {self.name}: {e}") from e

    @property
    def kind(self):
        return Source.open(self.source, self.base).kind if self.source else None

    def tables(self):
        return sorted({c.split(".")[0] for t in self.terms.values() for c in t.get("columns", [])} |
                      {x.split(".")[0] for r in self.relations for x in r})

    def certified(self, term):
        return bool(self.terms[term].get("certified"))

    def term_of_column(self, col):
        return [n for n, t in self.terms.items() if col in t.get("columns", [])]

    def values(self):
        """Distinct values of short text columns, for matching filter values in questions."""
        if self._values is None:
            self._values = {}
            try:
                src = self.connect()
            except OntologyError:
                return self._values
            with src:
                types = {}
                for n, t in self.terms.items():
                    for col in t.get("columns", []):
                        tb, c = col.split(".")
                        if tb not in types:
                            try:
                                types[tb] = {x[0]: x[1] for x in src.columns(tb)}
                            except src.errors:
                                types[tb] = {}
                        if not Source.is_text(types[tb].get(c, "TEXT")) or c not in types[tb]:
                            continue
                        try:
                            rows = src.rows(f'SELECT DISTINCT "{c}" FROM "{tb}" WHERE "{c}" IS NOT NULL LIMIT 201')
                        except src.errors:
                            continue
                        if 0 < len(rows) <= 200:
                            self._values[col] = [r[0] for r in rows if isinstance(r[0], str) and 0 < len(r[0]) <= 60]
        return self._values

    def schema(self, src):
        return {t: {c[0]: c[1] for c in src.columns(t)} for t in src.tables()}

    # ── checking an ontology against its data ───────────────────────────────────────────────────────────────
    def check(self):
        """Problems found by comparing the declarations with the data source: list of (severity, message)."""
        out = []
        try:
            src = self.connect()
        except OntologyError as e:
            return [("error", str(e))]
        with src:
            schema = self.schema(src)
            for n, t in self.terms.items():
                for col in t.get("columns", []):
                    tb, c = col.split(".")
                    if tb not in schema:
                        out.append(("error", f"term {n}: table '{tb}' does not exist"))
                    elif c not in schema[tb]:
                        out.append(("error", f"term {n}: column '{col}' does not exist"))
            for a, b in self.relations:
                ta, ca = a.split(".")
                tb, cb = b.split(".")
                if ta not in schema or ca not in schema.get(ta, ()) or tb not in schema or cb not in schema.get(tb, ()):
                    out.append(("error", f"relation {a} -> {b}: unknown table or column"))
                    continue
                orphans = src.one(f'SELECT COUNT(*) FROM "{ta}" WHERE "{ca}" IS NOT NULL AND "{ca}" NOT IN '
                                  f'(SELECT "{cb}" FROM "{tb}")')[0]
                if orphans:
                    out.append(("warning", f"relation {a} -> {b}: {orphans} row(s) in {ta} have no match in {tb}"))
        for n, t in self.terms.items():
            if t.get("measure"):
                v = validate_sql(self, f"SELECT {t['measure']} FROM {_from_for(self, t['measure'])}", certify=False)
                out += [("error", f"term {n}: measure: {p}") for p in v["problems"]]
        for n, t in self.terms.items():
            if not t.get("certified"):
                out.append(("info", f"term {n} is not certified yet"))
        return out


def _from_for(onto, sql):
    """FROM clause for a measure: its tables, joined along declared relations."""
    tables = sorted(set(re.findall(r"\b([A-Za-z_]\w*)\.[A-Za-z_]\w*", sql)))
    if len(tables) <= 1:
        return tables[0] if tables else "(SELECT 1) AS one"
    joins = _join_path(onto, tables[0], set(tables))
    if joins is None:
        return ", ".join(tables)
    return tables[0] + "".join(f" JOIN {t} ON {c}" for t, c in joins)


# ── discovery ────────────────────────────────────────────────────────────────────────────────────────────────
def _camel(words):
    return "".join(w[:1].upper() + w[1:] for w in words if w)


def _a(phrase):
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


GENERIC = {"name", "code", "type", "status", "title", "label", "description", "date", "number", "no"}


def _singular(w):
    return w[:-3] + "y" if w.endswith("ies") else w[:-1] if w.endswith("s") and not w.endswith("ss") else w


def discover(db, name=None, history=None):
    """Profile a database (SQLite, DuckDB or PostgreSQL) and propose an ontology: one entity term per table (with
    a count measure), one term per meaningful column, joins from declared foreign keys and from verified value
    inclusion, and measures for amounts (SUM), rates (AVG) and aggregates found in query history. Nothing is
    certified."""
    spec = str(db)
    src = Source.open(spec, Path.cwd())
    if not src.exists():
        raise OntologyError(f"no such database: {db}")
    src.connect()
    con = src
    tables = [t for t in src.tables() if not t.startswith("sqlite_")]
    info, pk, rels = {}, {}, []
    for t in tables:
        cols = src.columns(t)
        info[t] = cols
        keys = [c[0] for c in cols if c[2]]
        pk[t] = keys[0] if len(keys) == 1 else None
        for col, ref_t, ref_c in src.foreign_keys(t):
            rels.append((f"{t}.{col}", f"{ref_t}.{ref_c}", "declared foreign key"))
    known = {(a, b) for a, b, _ in rels}
    for t in tables:                                          # inferred joins: x_id columns whose values ⊆ a key
        for c in info[t]:
            col = c[0]
            if col == pk[t] or not col.lower().endswith("_id"):
                continue
            stem = col[:-3].lower()
            for u in tables:
                if u == t or not pk[u] or _singular(u.lower()) != stem and u.lower() != stem:
                    continue
                if (f"{t}.{col}", f"{u}.{pk[u]}") in known:
                    continue
                n, orphans = con.one(f'SELECT COUNT("{col}"), SUM(CASE WHEN "{col}" NOT IN (SELECT "{pk[u]}" FROM '
                                     f'"{u}") THEN 1 ELSE 0 END) FROM "{t}"')
                if n and not orphans:
                    rels.append((f"{t}.{col}", f"{u}.{pk[u]}", f"inferred: every {t}.{col} value is a {u}.{pk[u]}"))
    fk_cols = {a for a, _, _ in rels}
    terms, notes = {}, {}
    for t in tables:
        rows = con.one(f'SELECT COUNT(*) FROM "{t}"')[0]
        ent = _camel([_singular(w) for w in _words(t)])
        if pk[t]:
            ent_phrase = ' '.join(_singular(w) for w in _words(t))
            terms[ent] = dict(description=f"{_a(ent_phrase).capitalize()} ({t}, {rows:,} rows)",
                              synonyms=_syn([_singular(_words(t)[-1])]), columns=[f"{t}.{pk[t]}"],
                              measure=f"COUNT(DISTINCT {t}.{pk[t]})")
            notes[ent] = f"entity · {rows:,} rows"
        for c in info[t]:
            col, typ = c[0], (c[1] or "").upper()
            if col == pk[t] or f"{t}.{col}" in fk_cols:
                continue
            words = _words(col)
            tname = _camel(words)
            if set(words) <= GENERIC or tname in terms:
                tname = _camel([_singular(w) for w in _words(t)] + words)
            numeric = Source.is_number(typ)
            lo, hi, nd = con.one(f'SELECT MIN("{col}"), MAX("{col}"), COUNT(DISTINCT "{col}") FROM "{t}"')
            desc = f"{' '.join(words).capitalize()} of {_a(' '.join(_singular(w) for w in _words(t)))}"
            term = dict(description=desc, synonyms=_syn(words[-1:]), columns=[f"{t}.{col}"])
            if numeric and not any(w in ("year", "month", "day", "code", "zip", "pin") for w in words):
                ratio = lo is not None and hi is not None and 0 <= float(lo) and float(hi) <= 1 and "INT" not in typ
                agg = "AVG" if ratio or any(w in ("price", "rate", "score", "ratio", "pct", "percent", "age")
                                            for w in words) else "SUM"
                term["measure"] = f"{agg}({t}.{col})"
                notes[tname] = f"{typ or 'number'} · {lo} to {hi}"
            else:
                notes[tname] = f"{typ or 'text'} · {nd:,} distinct" + (f" · e.g. {lo!s:.20}" if lo is not None else "")
            terms[tname] = term
    for i, (expr, alias) in enumerate(_history_measures(history) if history else []):
        tname = _camel(_words(alias)) or f"Measure{i + 1}"
        cols = sorted(set(re.findall(r"\b[A-Za-z_]\w*\.[A-Za-z_]\w*", expr)))
        same = next((n for n, t in terms.items() if re.sub(r"\s+", "", t.get("measure", "")).lower() ==
                     re.sub(r"\s+", "", expr).lower()), None)
        if same:                    # the business already has a name for this measure: rename the term to it
            terms = {(tname if n == same else n): t for n, t in terms.items()}
            terms[tname]["description"] = f"{' '.join(_words(alias)).capitalize()}: {terms[tname]['description'][0].lower()}" \
                                          f"{terms[tname]['description'][1:]} (named in query history)"
            terms[tname]["synonyms"] = list(dict.fromkeys(_syn(_words(alias)) + terms[tname]["synonyms"]))[:4]
            notes[tname] = notes.pop(same, "") + " · named in query history"
            continue
        if cols and tname not in terms:
            terms[tname] = dict(description=f"{' '.join(_words(alias)).capitalize()} (from query history)",
                                synonyms=_syn(_words(alias)), columns=cols, measure=expr)
            notes[tname] = "from query history"
    src.close()
    used = {n.lower() for n in terms}                   # a word may name only one term (compile check E136)
    for n, t in terms.items():
        keep = []
        for sy in t.get("synonyms", []):
            if sy.lower() not in used and _camel(_words(sy)).lower() not in used:
                keep.append(sy)
                used.add(sy.lower())
        t["synonyms"] = keep
    if src.kind == "postgresql":                            # never write a password into source code
        source, base = re.sub(r"//([^:/@]+):[^@]*@", r"//\1:${PGPASSWORD}@", spec), Path.cwd()
        name = name or _camel(_words(spec.rsplit("/", 1)[-1].split("?")[0])) or "Data"
    else:
        p = src.path
        source = (("duckdb:" if spec.lower().startswith("duckdb:") else "") + p.name)
        base = p.parent
        name = name or _camel(_words(p.stem)) or "Data"
    return Ontology(name, source, terms, [(a, b) for a, b, _ in rels], base), notes, rels


def _syn(words):
    out = []
    for w in words:
        out += [s for s in SYNONYMS.get(w, []) if s not in out]
    return out[:4]


def _split_top(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def _history_measures(path):
    """Aggregate select items with an alias in a query log, e.g. SUM(a.x * b.y) - SUM(a.z) AS discount_given."""
    text = re.sub(r"--[^\n]*", "", Path(path).read_text(encoding="utf-8", errors="replace"))
    found = []
    for m in re.finditer(r"(?is)\bselect\b(.*?)\bfrom\b", text):
        for item in _split_top(m.group(1)):
            mm = re.match(r"(?is)\s*(.+?)\s+as\s+([A-Za-z_]\w*)\s*$", item)
            if not mm or not re.search(r"(?i)\b(sum|avg|count|min|max)\s*\(", mm.group(1)):
                continue
            expr, alias = re.sub(r"\s+", " ", mm.group(1)).strip(), mm.group(2)
            if (expr, alias) not in found:
                found.append((expr, alias))
    return found


def to_source(onto, notes=None, rels=None):
    """AlgoLang source for an ontology: what `algo ontology discover` writes for people to review and certify."""
    notes, why = notes or {}, {(a, b): w for a, b, w in (rels or [])}
    q = lambda s: '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'
    shown = re.sub(r"//[^@/]*@", "//", onto.source or "")
    L = [f"// AlgoOnto™: discovered by `algo onto discover` from {shown}. Review every term, then certify it:",
         f"//   algo onto certify <this file> <Term> --by <reviewer>", "",
         f"ontology {onto.name} from {q(onto.source)} {{"]
    for n, t in onto.terms.items():
        L.append(f"    term {n} {q(t.get('description', ''))} {{" + (f"   // {notes[n]}" if n in notes else ""))
        if t.get("synonyms"):
            L.append("        synonyms " + ", ".join(q(s) for s in t["synonyms"]))
        L.append("        column " + ", ".join(t["columns"]))
        if t.get("measure"):
            L.append(f"        measure {q(t['measure'])}")
        if t.get("certified"):
            L.append(f"        certified {q(t['certified'])}" + (f" on {q(t['on'])}" if t.get("on") else ""))
        L.append("    }")
    for a, b in onto.relations:
        L.append(f"    relation {a} -> {b}" + (f"   // {why[(a, b)]}" if (a, b) in why else ""))
    L.append("}")
    return "\n".join(L) + "\n"


# ── retrieval and planning ───────────────────────────────────────────────────────────────────────────────────
def _vocab(n, t):
    v = {}
    for w in _words(n):
        v[_stem(w)] = 3.0
    for s in t.get("synonyms", []):
        for w in _words(s):
            v.setdefault(_stem(w), 2.5)
    for c in t.get("columns", []):
        for w in _words(c.split(".")[1]):
            v.setdefault(_stem(w), 1.5)
    for w in _words(t.get("description", "")):
        if w not in STOP:
            v.setdefault(_stem(w), 0.5)
    return v


def search(onto, question, k=5):
    """Terms ranked by how well they match the question (names and synonyms count most)."""
    qw = [_stem(w) for w in _words(question) if w not in STOP]
    scored = []
    for n, t in onto.terms.items():
        v = _vocab(n, t)
        s = sum(v.get(w, 0) for w in set(qw))
        if s > 0:
            scored.append((round(s, 2), n))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[:k]


def _join_path(onto, start, need):
    """Tables to join (as (table, on-condition)) so that every table in `need` is reachable from `start`, using
    only declared relations. None if some table cannot be reached."""
    adj = {}
    for a, b in onto.relations:
        ta, tb = a.split(".")[0], b.split(".")[0]
        adj.setdefault(ta, []).append((tb, f"{a} = {b}"))
        adj.setdefault(tb, []).append((ta, f"{a} = {b}"))
    prev = {start: None}
    dq = deque([start])
    while dq:
        x = dq.popleft()
        for y, cond in adj.get(x, []):
            if y not in prev:
                prev[y] = (x, cond)
                dq.append(y)
    joins, seen = [], {start}
    for t in sorted(need - {start}):
        if t not in prev:
            return None
        chain, cur = [], t
        while cur not in seen:
            p, cond = prev[cur]
            chain.append((cur, cond))
            cur = p
        for tb, cond in reversed(chain):
            if tb not in seen:
                joins.append((tb, cond))
                seen.add(tb)
    return joins


def _dim_column(onto, frag, measure):
    """The column to group by for a phrase such as 'region' or 'products' (an entity groups by its name)."""
    for _s, n in search(onto, frag, k=6):
        t = onto.terms[n]
        if n == measure or not t.get("columns"):
            continue
        m = t.get("measure", "")
        if m.upper().startswith("COUNT"):                   # an entity: group by its name-like column
            table = t["columns"][0].split(".")[0]
            named = [c for x, tt in onto.terms.items() for c in tt.get("columns", [])
                     if c.startswith(table + ".") and not tt.get("measure") and "name" in c.lower()]
            return (n, named[0] if named else t["columns"][0])
        if m:                                               # a numeric measure is not a grouping
            continue
        return (n, t["columns"][0])
    return None


def plan(onto, question):
    """A query plan built only from declared terms, measures and relations, or the reason there is none."""
    ql = " ".join(question.lower().replace("?", " ").split())
    count_q = bool(re.search(r"\bhow many\b|\bnumber of\b|\bcount\b", ql))
    order, dim_frags = None, []
    top = re.search(r"\b(top|bottom|highest|lowest|largest|smallest|best|worst)\s*(\d+)?\s+([a-z][a-z ]*?)\s+by\s+(.+)", ql)
    if top:                                                 # "top 3 products by sales"
        desc = top.group(1) in ("top", "highest", "largest", "best")
        order = ("DESC" if desc else "ASC", int(top.group(2) or (5 if top.group(1) in ("top", "bottom") else 1)))
        measure_text, dim_frags = top.group(4), [top.group(3)]
    else:                                                   # "net revenue by region in 2025"
        parts = re.split(r"\b(?:by|per|for each|each|across)\b", ql, maxsplit=1)
        measure_text = parts[0]
        dim_frags = [" ".join(m.group(1).split()[:3]) for m in
                     re.finditer(r"\b(?:by|per|each|across)\s+([a-z][a-z0-9 ]{1,40})", ql)]
        hl = re.search(r"\b(highest|lowest|largest|smallest|best|worst)\b", ql)
        if hl:
            order = ("DESC" if hl.group(1) in ("highest", "largest", "best") else "ASC", 1)
    def measures_for(text):
        scored = []
        for sc, n in search(onto, text, k=12):
            m = onto.terms[n].get("measure")
            if not m:
                continue
            is_count = m.upper().startswith("COUNT")
            scored.append((sc + (2 if count_q and is_count else 0) - (0.25 if is_count and not count_q else 0), n))
        return [n for _s, n in sorted(scored, key=lambda x: (-x[0], x[1]))]
    measures = measures_for(measure_text) or measures_for(ql)
    if not measures:
        close = ", ".join(n for _s, n in search(onto, question, k=3)) or "none"
        return dict(answerable=False, reason=f"no defined measure matches the question (closest terms: {close})")
    measure = measures[0]
    dims = []
    for frag in dim_frags:
        d = _dim_column(onto, frag, measure)
        if d is None:                       # never drop a grouping the question asked for
            return dict(answerable=False, reason=f"no defined term can group the answer by '{frag.strip()}'")
        if d not in dims:
            dims.append(d)
    filters = []
    qwords = {_stem(w) for w in _words(ql)}
    for col, vs in onto.values().items():                  # known text values named in the question
        for v in sorted(vs, key=lambda x: -len(str(x))):
            if re.search(r"(?<![a-z0-9])" + re.escape(str(v).lower()) + r"(?![a-z0-9])", ql):
                filters.append((col, "=", v))
                break
    by_value = {}
    for col, op, v in filters:                              # a value in several columns: keep the one the question names
        by_value.setdefault(str(v).lower(), []).append((col, op, v))
    filters = []
    for v, cands in by_value.items():
        named = [c for c in cands if any(set(_vocab(n, onto.terms[n])) & qwords - {_stem(v)}
                                         for n in onto.term_of_column(c[0]))]
        filters.append((named or cands)[0])
    filters = [f for f in filters if not any(d[1] == f[0] for d in dims)]
    years = re.findall(r"\b(19\d\d|20\d\d)\b", ql)
    if years:
        dcols = [c for n, t in onto.terms.items() for c in t.get("columns", []) if
                 any(w in ("date", "day", "time", "at", "on") for w in _words(c.split(".")[1]))]
        if not dcols:
            return dict(answerable=False, reason=f"the question names a year ({years[0]}) but no date term is defined")
        mt = onto.terms[measure]["columns"][0].split(".")[0]
        dcol = sorted(dcols, key=lambda c: (c.split(".")[0] != mt, c))[0]
        filters.append((Source.open(onto.source, onto.base).year_expr(dcol) if onto.source else
                        f"strftime('%Y', {dcol})", "=", years[0]))
    if order and not dims:
        order = None
    mexpr = onto.terms[measure]["measure"]
    tables_needed = {c.split(".")[0] for c in re.findall(r"\b[A-Za-z_]\w*\.[A-Za-z_]\w*", mexpr)}
    base = sorted(tables_needed)[0] if tables_needed else onto.terms[measure]["columns"][0].split(".")[0]
    need = tables_needed | {d[1].split(".")[0] for d in dims} | \
        {re.findall(r"([A-Za-z_]\w*)\.", f[0])[0] for f in filters}
    joins = _join_path(onto, base, need)
    if joins is None:
        return dict(answerable=False, reason="no declared relation connects " + ", ".join(sorted(need)))
    q = lambda a: '"' + a + '"'
    sel = [f"{d[1]} AS {q(d[0])}" for d in dims] + [f"{mexpr} AS {q(measure)}"]
    sql = f"SELECT {', '.join(sel)} FROM {base}" + "".join(f" JOIN {t} ON {c}" for t, c in joins)
    params = []
    if filters:
        sql += " WHERE " + " AND ".join(f"{c} {op} ?" for c, op, _v in filters)
        params = [v for _c, _o, v in filters]
    if dims:
        sql += " GROUP BY " + ", ".join(d[1] for d in dims)
        sql += f" ORDER BY {q(measure)} {order[0]} LIMIT {order[1]}" if order else \
            f" ORDER BY {q(measure)} DESC LIMIT {MAX_ROWS}"
    fterms = []
    for c, _o, _v in filters:
        cols = re.findall(r"\w+\.\w+", c)
        fterms += onto.term_of_column(cols[0]) if cols else []
    used = [measure] + [d[0] for d in dims] + fterms
    return dict(answerable=True, sql=sql, params=params, measure=measure, dims=[d[0] for d in dims],
                filters=[(c, v) for c, _o, v in filters], terms=list(dict.fromkeys(used)),
                tables=sorted({base} | {t for t, _c in joins}))


# ── validation ───────────────────────────────────────────────────────────────────────────────────────────────
def _norm(s):
    return re.sub(r"\s+", "", str(s)).lower()


def validate_sql(onto, sql, certify=True, params=()):
    """Check SQL against the ontology: one read-only SELECT; only mapped tables; joins only on declared relations;
    aggregates only as defined measures (certified ones when `certify`); filter values that exist; and that the
    database can compile it. Returns {ok, problems, terms, uncertified}."""
    problems, s = [], sql.strip().rstrip(";")
    if ";" in s:
        problems.append("more than one statement")
    if not re.match(r"(?is)^\s*(with\b.*?\)\s*)?select\b", s):
        problems.append("only SELECT queries are allowed")
    if SQL_FORBIDDEN.search(re.sub(r"'[^']*'", "''", s)):
        problems.append("the query modifies data or the database: " + SQL_FORBIDDEN.search(s).group(1).upper())
    mapped = set(onto.tables())
    tables = set(re.findall(r"(?i)\b(?:from|join)\s+\"?([A-Za-z_]\w*)", s))
    for t in sorted(tables - mapped):
        problems.append(f"table '{t}' is not part of ontology {onto.name}")
    rels = {_norm(f"{a}={b}") for a, b in onto.relations} | {_norm(f"{b}={a}") for a, b in onto.relations}
    for cond in re.findall(r"(?i)\bjoin\s+\w+(?:\s+\w+)?\s+on\s+([\w.]+\s*=\s*[\w.]+)", s):
        if _norm(cond) not in rels:
            problems.append(f"join on {cond.strip()} is not a declared relation")
    terms_used, uncertified = [], []
    rest = s
    for n, t in sorted(((n, t) for n, t in onto.terms.items() if t.get("measure")),
                       key=lambda x: -len(x[1]["measure"])):   # whole measures first: SUM(a*b) - SUM(c)
        m = re.sub(r"\s+", "", t["measure"])
        pat = r"\s*".join(re.escape(ch) for ch in m)
        rest, k = re.subn(pat, " § ", rest, flags=re.I)
        if k and n not in terms_used:
            terms_used.append(n)
            if certify and not onto.certified(n):
                uncertified.append(n)
    for agg in re.findall(r"(?i)\b(?:sum|avg|count|min|max)\s*\((?:[^()]|\([^()]*\))*\)", rest):
        problems.append(f"{agg} is not a defined measure (define it as a term's `measure` and certify it)")
    for col in sorted(set(re.findall(r"\b([A-Za-z_]\w*\.[A-Za-z_]\w*)\b", rest))):
        for n in onto.term_of_column(col):
            if n not in terms_used and not onto.terms[n].get("measure"):
                terms_used.append(n)
    if not problems:
        try:
            src = onto.connect()
        except OntologyError as e:
            problems.append(str(e))
        else:
            with src:
                try:
                    src.explain(s, params)
                    for col, val in re.findall(r"\b([A-Za-z_]\w*\.[A-Za-z_]\w*)\s*=\s*'([^']*)'", s):
                        tb, c = col.split(".")
                        if not src.one(f'SELECT 1 FROM "{tb}" WHERE "{c}" = ? LIMIT 1', (val,)):
                            problems.append(f"no row has {col} = '{val}'")
                except src.errors as e:
                    problems.append(f"the database rejects the query: {str(e).strip().splitlines()[0]}")
    return dict(ok=not problems and not uncertified, problems=problems, terms=terms_used, uncertified=uncertified)


# ── answering ────────────────────────────────────────────────────────────────────────────────────────────────
def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def ask(onto, question):
    """Answer a question from the data using certified definitions only. Never guesses: unanswerable questions
    and uncertified definitions are reported as such."""
    p = plan(onto, question)
    if not p["answerable"]:
        return dict(status="unanswerable", question=question, reason=p["reason"], ontology=onto.name)
    v = validate_sql(onto, p["sql"], params=p["params"])
    lineage = dict(ontology=onto.name, terms=p["terms"], tables=p["tables"], sql=p["sql"], params=p["params"],
                   certified=[t for t in p["terms"] if onto.certified(t)],
                   uncertified=[t for t in p["terms"] if not onto.certified(t)])
    if v["problems"]:
        return dict(status="invalid", question=question, reason="; ".join(v["problems"]), **lineage)
    with onto.connect() as src:
        cur = src.execute(p["sql"], p["params"])
        cols = [d[0] for d in cur.description]
        rows = [tuple(float(x) if type(x).__name__ == "Decimal" else x for x in r) for r in cur.fetchmany(MAX_ROWS)]
    status = "answered" if not lineage["uncertified"] else "uncertified"
    if len(rows) == 1 and len(cols) == 1:
        text = f"{p['measure']}: {_fmt(rows[0][0])}"
    else:
        text = "\n".join(" · ".join(f"{c}: {_fmt(x)}" for c, x in zip(cols, r)) for r in rows) or "no rows"
    return dict(status=status, question=question, answer=text, columns=cols, rows=[list(r) for r in rows], **lineage)


def render_answer(a):
    if a["status"] == "unanswerable":
        return f"UNANSWERABLE from ontology {a['ontology']}: {a['reason']}."
    if a["status"] == "invalid":
        return f"NOT ANSWERED: the planned query failed validation: {a['reason']}."
    head = a["answer"]
    cert = "all terms certified" if not a["uncertified"] else \
        f"⚠ UNCERTIFIED terms: {', '.join(a['uncertified'])} (certify them before relying on this answer)"
    params = f"   params {a['params']}" if a["params"] else ""
    return f"{head}\nSQL: {a['sql']}{params}\nTerms: {', '.join(a['terms'])} · {cert}"


# ── drift (v1.4): has the data moved away from the certified definitions? ─────────────────────────────────────
def _family(typ):
    t = (typ or "").upper()
    if "BOOL" in t:
        return "boolean"
    if any(k in t for k in ("DATE", "TIME")):
        return "date"
    if Source.is_number(t):
        return "number"
    return "text"


def snapshot(onto):
    """What the data looks like now, as far as the ontology is concerned: every table and column with its type
    and row count, the values of mapped text columns, and every measure's current value. Kept next to the
    ontology (and reviewed with it), it is the baseline that `drift` compares against."""
    with onto.connect() as src:
        tables = {}
        for t in src.tables():
            if t.startswith("sqlite_"):
                continue
            tables[t] = dict(rows=src.one(f'SELECT COUNT(*) FROM "{t}"')[0],
                             columns={c[0]: c[1] for c in src.columns(t)})
    values = {}                                    # categories only: few distinct values relative to rows
    for col, vs in onto.values().items():
        rows = tables.get(col.split(".")[0], {}).get("rows", 0)
        if len(vs) <= 50 and rows and len(vs) / rows <= 0.5:
            values[col] = sorted(map(str, vs))
    measures = {}
    for n, t in onto.terms.items():
        if t.get("measure"):
            try:
                with onto.connect() as src:
                    v = src.one(f"SELECT {t['measure']} FROM {_from_for(onto, t['measure'])}")[0]
                measures[n] = float(v) if v is not None else None
            except Exception:  # a broken measure is reported by check and drift, not here
                measures[n] = None
    return dict(algoonto=1, ontology=onto.name, source_kind=onto.kind, taken=time.strftime("%Y-%m-%dT%H:%M:%S"),
                tables=tables, values=values, measures=measures,
                certified={n: t.get("certified") for n, t in onto.terms.items()})


def drift(onto, snap, tolerance=0.25):
    """Compare the data now with a snapshot. Returns findings (severity, kind, message, terms):
       breaking   a mapped table or column is gone, or its type changed; a measure no longer runs
       warning    a mapped table's rows or a measure's value moved by more than `tolerance`;
                  a mapped text column gained or lost values (new regions, channels, categories …)
       info       tables or columns the ontology does not cover yet (candidate terms)
    plus a `review` finding for every certified term touched by a breaking or warning finding."""
    now = snapshot(onto)
    out = []

    def add(sev, kind, msg, terms=()):
        out.append(dict(severity=sev, kind=kind, message=msg, terms=sorted(set(terms))))

    col_terms = {}
    for n, t in onto.terms.items():
        for c in t.get("columns", []):
            col_terms.setdefault(c, []).append(n)
        for c in re.findall(r"\b([A-Za-z_]\w*\.[A-Za-z_]\w*)\b", t.get("measure") or ""):
            col_terms.setdefault(c, []).append(n)
    for a, b in onto.relations:
        for c in (a, b):
            col_terms.setdefault(c, [])
    then_t, now_t = snap.get("tables", {}), now["tables"]
    for col, terms in sorted(col_terms.items()):
        tb, c = col.split(".")
        if tb not in now_t:
            add("breaking", "table removed", f"table {tb} no longer exists (used by {col})", terms)
        elif c not in now_t[tb]["columns"]:
            renamed = [x for x in now_t[tb]["columns"] if x not in then_t.get(tb, {}).get("columns", {})]
            hint = f"; new column(s) in {tb}: {', '.join(renamed)} (renamed?)" if renamed else ""
            add("breaking", "column removed", f"column {col} no longer exists{hint}", terms)
        else:
            was = then_t.get(tb, {}).get("columns", {}).get(c)
            is_ = now_t[tb]["columns"][c]
            if was and _family(was) != _family(is_):
                add("breaking", "type changed", f"column {col} changed type: {was} → {is_}", terms)
    for tb in sorted({c.split(".")[0] for c in col_terms} & set(then_t) & set(now_t)):
        r0, r1 = then_t[tb]["rows"], now_t[tb]["rows"]
        if r0 and abs(r1 - r0) / r0 > tolerance:
            terms = [n for c, ts in col_terms.items() if c.startswith(tb + ".") for n in ts]
            add("warning", "rows changed", f"table {tb}: {r0:,} → {r1:,} rows ({(r1 - r0) / r0:+.0%})", terms)
    for n, v0 in snap.get("measures", {}).items():
        if n not in onto.terms or not onto.terms[n].get("measure"):
            continue
        v1 = now["measures"].get(n)
        if v1 is None and v0 is not None:
            add("breaking", "measure failed", f"measure {n} ({onto.terms[n]['measure']}) no longer runs", [n])
        elif v0 and v1 is not None and abs(v1 - v0) / abs(v0) > tolerance:
            add("warning", "measure moved", f"measure {n}: {v0:,.2f} → {v1:,.2f} ({(v1 - v0) / abs(v0):+.0%})", [n])
    for col, vs in now["values"].items():
        before = set(snap.get("values", {}).get(col, []))
        if not before:
            continue
        new, gone = sorted(set(vs) - before), sorted(before - set(vs))
        terms = col_terms.get(col, [])
        if new:
            add("warning", "new values", f"{col} has new value(s): {', '.join(new[:8])}"
                                         f"{' …' if len(new) > 8 else ''}", terms)
        if gone:
            add("warning", "values gone", f"{col} lost value(s): {', '.join(gone[:8])}", terms)
    mapped = set(col_terms)
    for tb, info in sorted(now_t.items()):
        if tb not in then_t:
            add("info", "new table", f"new table {tb} ({info['rows']:,} rows) is not in the ontology")
            continue
        extra = [c for c in info["columns"] if f"{tb}.{c}" not in mapped and c not in then_t[tb]["columns"]]
        if extra:
            add("info", "new columns", f"new column(s) in {tb} not in the ontology: {', '.join(extra)}")
    touched = sorted({n for f in out if f["severity"] in ("breaking", "warning") for n in f["terms"]
                      if onto.terms.get(n, {}).get("certified")})
    for n in touched:
        sev = "breaking" if any(n in f["terms"] for f in out if f["severity"] == "breaking") else "warning"
        add(sev, "review", f"certification of {n} (by {onto.terms[n]['certified']}) should be reviewed", [n])
    return out


def snapshot_path(file, name):
    """retail.onto.algo → retail.onto.snapshot.json (one ontology per file; --name picks another)."""
    p = Path(file)
    return p.with_name(f"{p.stem}.snapshot.json")


# ── export (v1.4): OWL/RDF (Turtle) and JSON-LD ─────────────────────────────────────────────────────────────
ALGO_NS = "https://github.com/drssnaiml1-cell/algolang/ns/onto#"
PREFIXES = {"owl": "http://www.w3.org/2002/07/owl#", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#", "skos": "http://www.w3.org/2004/02/skos/core#",
            "dcterms": "http://purl.org/dc/terms/", "xsd": "http://www.w3.org/2001/XMLSchema#", "algo": ALGO_NS}


def _entity_of_table(onto):
    """table → entity term (a term whose measure counts the table's key)."""
    out = {}
    for n, t in onto.terms.items():
        m = (t.get("measure") or "").upper().replace(" ", "")
        if m.startswith("COUNT(") and len(t.get("columns", [])) == 1:
            out.setdefault(t["columns"][0].split(".")[0], n)
    return out


def to_triples(onto, base=None):
    """The ontology as RDF triples (subject, predicate, object); objects are ("iri", x) or ("lit", value, type).
       entity terms → owl:Class · other terms → owl:DatatypeProperty (rdfs:domain = the entity of their table)
       relations → owl:ObjectProperty · synonyms → skos:altLabel · description → skos:definition
       columns, measures, joins and certification → the algo: vocabulary (column, measure, join, certifiedBy …)."""
    base = base or f"urn:algolang:onto:{onto.name}#"
    I = lambda x: ("iri", x)                                       # noqa: E731
    L = lambda v, t=None: ("lit", v, t)                            # noqa: E731
    P = lambda p: PREFIXES[p.split(":")[0]] + p.split(":")[1]      # noqa: E731
    ents = _entity_of_table(onto)
    me = base.rstrip("#/")
    tr = [(me, P("rdf:type"), I(P("owl:Ontology"))), (me, P("rdfs:label"), L(f"{onto.name} (AlgoOnto™)")),
          (me, P("dcterms:source"), L(Source.open(onto.source, onto.base).path.name if onto.source and
                                       Source.open(onto.source, onto.base).kind != "postgresql" else
                                       re.sub(r"//[^@/]*@", "//", onto.source or "")))]
    for n, t in onto.terms.items():
        s = base + n
        is_ent = ents.get(t["columns"][0].split(".")[0]) == n if t.get("columns") else False
        tr.append((s, P("rdf:type"), I(P("owl:Class" if is_ent else "owl:DatatypeProperty"))))
        tr.append((s, P("rdfs:label"), L(n)))
        tr.append((s, P("rdfs:isDefinedBy"), I(me)))
        if t.get("description"):
            tr.append((s, P("skos:definition"), L(t["description"])))
        for syn in t.get("synonyms", []):
            tr.append((s, P("skos:altLabel"), L(syn)))
        for c in t.get("columns", []):
            tr.append((s, P("algo:column"), L(c)))
        if not is_ent and t.get("columns"):
            dom = ents.get(t["columns"][0].split(".")[0])
            if dom:
                tr.append((s, P("rdfs:domain"), I(base + dom)))
        if t.get("measure"):
            tr.append((s, P("algo:measure"), L(t["measure"])))
        tr.append((s, P("algo:status"), L("certified" if t.get("certified") else "proposed")))
        if t.get("certified"):
            tr.append((s, P("algo:certifiedBy"), L(t["certified"])))
            if t.get("on"):
                tr.append((s, P("algo:certifiedOn"), L(t["on"], P("xsd:date"))))
    for a, b in onto.relations:
        ta, tb = a.split(".")[0], b.split(".")[0]
        s = base + "join_" + re.sub(r"\W", "_", a)
        tr += [(s, P("rdf:type"), I(P("owl:ObjectProperty"))), (s, P("rdfs:label"), L(f"{a} → {b}")),
               (s, P("algo:join"), L(f"{a} = {b}")), (s, P("rdfs:isDefinedBy"), I(me))]
        if ta in ents:
            tr.append((s, P("rdfs:domain"), I(base + ents[ta])))
        if tb in ents:
            tr.append((s, P("rdfs:range"), I(base + ents[tb])))
    return tr


def _ttl_lit(v, t=None):
    esc = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{esc}"' + (f"^^<{t}>" if t else "")


def to_turtle(onto, base=None):
    def short(iri):
        for p, ns in PREFIXES.items():
            if iri.startswith(ns) and re.fullmatch(r"[A-Za-z_][\w-]*", iri[len(ns):]):
                return f"{p}:{iri[len(ns):]}"
        return f"<{iri}>"
    out = [f"@prefix {p}: <{ns}> ." for p, ns in PREFIXES.items()]
    out.append(f"# AlgoOnto™ export of ontology {onto.name} (AlgoLang {__import__('algoruntime').VERSION})")
    by = {}
    for s_, p_, o in to_triples(onto, base):
        by.setdefault(s_, []).append((p_, o))
    for s_, pos in by.items():
        lines = []
        for p_, o in pos:
            obj = short(o[1]) if o[0] == "iri" else _ttl_lit(o[1], o[2])
            lines.append(f"    {'a' if p_ == PREFIXES['rdf'] + 'type' else short(p_)} {obj}")
        out.append(f"\n{short(s_)}\n" + " ;\n".join(lines) + " .")
    return "\n".join(out) + "\n"


def to_jsonld(onto, base=None):
    nodes = {}
    for s_, p_, o in to_triples(onto, base):
        n = nodes.setdefault(s_, {"@id": s_})
        if p_ == PREFIXES["rdf"] + "type":
            n.setdefault("@type", []).append(o[1])
            continue
        val = {"@id": o[1]} if o[0] == "iri" else ({"@value": o[1], "@type": o[2]} if o[2] else o[1])
        n.setdefault(p_, []).append(val)
    return {"@context": {k: v for k, v in PREFIXES.items()}, "@graph": list(nodes.values())}


# ── graph view (v1.4): entities, joins and certification at a glance ──────────────────────────────────────────
def graph_svg(onto):
    """An SVG picture of the ontology: one card per table (its entity and terms, measures in gold, a ✓ for every
    certified term) laid out left to right along the declared joins, which are drawn as labelled arrows."""
    from html import escape as e
    ents = _entity_of_table(onto)
    tables = onto.tables()
    by_table = {t: [] for t in tables}
    for n, t in onto.terms.items():
        if t.get("columns"):
            by_table.setdefault(t["columns"][0].split(".")[0], []).append(n)
    refs = {t: set() for t in by_table}                   # child table → parent tables (child.x_id -> parent.id)
    for a, b in onto.relations:
        refs.setdefault(a.split(".")[0], set()).add(b.split(".")[0])
        refs.setdefault(b.split(".")[0], set())
    col = {t: 0 for t in refs}                            # a table sits one column right of the tables that use it
    for _ in range(len(refs)):
        changed = False
        for child, parents in refs.items():
            for par in parents:
                if par != child and col[par] < col[child] + 1 and col[child] + 1 < len(refs):
                    col[par] = col[child] + 1
                    changed = True
        if not changed:
            break
    cols = {}
    for t in sorted(refs, key=lambda x: (col[x], -len(by_table.get(x, [])), x)):
        cols.setdefault(col[t], []).append(t)
    W, ROW, HEAD, GAPX, GAPY, PAD = 300, 22, 52, 120, 34, 24
    pos, ymax = {}, 0
    for ci in sorted(cols):
        y = PAD + 30
        for t in cols[ci]:
            h = HEAD + ROW * max(1, len(by_table.get(t, []))) + 12
            pos[t] = (PAD + ci * (W + GAPX), y, h)
            y += h + GAPY
        ymax = max(ymax, y)
    width = PAD * 2 + (max(cols or [0]) + 1) * W + max(cols or [0]) * GAPX
    height = ymax + PAD
    g = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
         f'font-family="Calibri, Segoe UI, Arial, sans-serif" role="img" aria-label="Ontology {e(onto.name)}">',
         f'<rect width="{width}" height="{height}" rx="12" fill="#FFFFFF"/>',
         '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
         'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#C9A227"/></marker></defs>',
         f'<text x="{PAD}" y="{PAD + 6}" font-size="18" font-weight="700" fill="#0B1F3A">{e(onto.name)}'
         f'<tspan dx="12" font-weight="400" fill="#5A6270" font-size="13">AlgoOnto™ · '
         f'{sum(1 for n in onto.terms if onto.certified(n))}/{len(onto.terms)} terms certified · '
         f'{len(onto.relations)} joins</tspan></text>']
    for a, b in onto.relations:                            # arrows first, under the cards
        ta, tb = a.split(".")[0], b.split(".")[0]
        if ta not in pos or tb not in pos:
            continue
        xa, ya, ha = pos[ta]
        xb, yb, hb = pos[tb]
        x1, y1 = (xa + W, ya + 26) if xb > xa else (xa, ya + 26)
        x2, y2 = (xb, yb + 26) if xb > xa else (xb + W, yb + 26)
        mx = (x1 + x2) / 2
        g.append(f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" fill="none" stroke="#C9A227" '
                 f'stroke-width="2" marker-end="url(#arr)"/>')
        g.append(f'<text x="{mx}" y="{(y1 + y2) / 2 - 6}" font-size="11" text-anchor="middle" fill="#5A6270">'
                 f'{e(a.split(".")[1])} → {e(b.split(".")[1])}</text>')
    for t, (x, y, h) in pos.items():
        ent = ents.get(t)
        cert_all = all(onto.certified(n) for n in by_table.get(t, [])) and by_table.get(t)
        g.append(f'<rect x="{x}" y="{y}" width="{W}" height="{h}" rx="10" fill="#FFFFFF" stroke="#D5DCE6"/>')
        g.append(f'<path d="M{x},{y + 10} a10,10 0 0 1 10,-10 h{W - 20} a10,10 0 0 1 10,10 v{HEAD - 18} h-{W} z" '
                 f'fill="#0B1F3A"/>')
        g.append(f'<text x="{x + 14}" y="{y + 22}" font-size="15" font-weight="700" fill="#FFFFFF">'
                 f'{e(ent or t)}</text>')
        g.append(f'<text x="{x + 14}" y="{y + 38}" font-size="11" fill="#C9A227" font-family="Consolas, monospace">'
                 f'{e(t)}</text>')
        if cert_all:
            g.append(f'<text x="{x + W - 12}" y="{y + 22}" font-size="11" text-anchor="end" fill="#C9A227">'
                     f'✓ certified</text>')
        for i, n in enumerate(by_table.get(t, [])):
            tm = onto.terms[n]
            ry = y + HEAD + 8 + i * ROW
            ok = onto.certified(n)
            g.append(f'<text x="{x + 14}" y="{ry + 9}" font-size="13" fill="{"#2F6B3A" if ok else "#B0B7C3"}">'
                     f'{"✓" if ok else "○"}</text>')
            g.append(f'<text x="{x + 32}" y="{ry + 9}" font-size="13" font-weight="{700 if n == ent else 400}" '
                     f'fill="#1B1B1B">{e(n)}</text>')
            right = tm.get("measure") or (tm["columns"][0].split(".")[1] if tm.get("columns") else "")
            if len(right) > 26:
                right = right[:25] + "…"
            g.append(f'<text x="{x + W - 12}" y="{ry + 9}" font-size="11" text-anchor="end" '
                     f'font-family="Consolas, monospace" fill="{"#A8861C" if tm.get("measure") else "#5A6270"}">'
                     f'{e(right)}</text>')
    g.append("</svg>")
    return "\n".join(g)


def graph_html(ontos, title="AlgoOnto™"):
    from html import escape as e
    parts = []
    for o in ontos:
        parts.append(f'<section><div class="scroll">{graph_svg(o)}</div><p class="note">Source '
                     f'<code>{e(re.sub(r"//[^@/]*@", "//", o.source or ""))}</code> · ✓ certified · ○ proposed (not '
                     f'certified) · <span class="m">gold</span> = certified SQL measure · arrows = declared joins</p>'
                     f'</section>')
    if not parts:
        parts.append("<p>No ontology found. Declare one with <code>ontology Name from \"data.db\" { … }</code>, or "
                     "discover one with <code>algo onto discover data.db</code>.</p>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>body{{margin:0;background:#F6F8FB;color:#1B1B1B;font:15px/1.5 Calibri,"Segoe UI",Arial,sans-serif}}
header{{background:#0B1F3A;color:#fff;padding:18px 28px;border-bottom:4px solid #C9A227}}
header h1{{margin:0;font:700 22px Cambria,Georgia,serif}} header p{{margin:2px 0 0;color:#E8EDF5;font-size:13px}}
header a{{color:#C9A227}} section{{background:#fff;margin:22px;border-radius:10px;padding:14px;
box-shadow:0 1px 3px rgba(11,31,58,.08)}} .scroll{{overflow-x:auto}} .note{{color:#5A6270;font-size:13px;margin:6px 4px}}
.m{{color:#A8861C;font-weight:700}} code{{font-size:12px}}</style></head><body>
<header><h1>AlgoOnto™ · ontology as code</h1><p>Business terms, certified measures and joins that AlgoLang
data agents are grounded in. <a href="/">← Studio</a></p></header>
{"".join(parts)}
</body></html>
"""


# ── runtime: tools for agents that are `grounded in` an ontology ───────────────────────────────────────────────
def register(name, data, base=None):
    REGISTRY[name] = Ontology.from_dict(data, base)
    return REGISTRY[name]


def install_tools(rt):
    """ontology.ask / ontology.search / ontology.term / ontology.validate for grounded agents. The ontology is
    the one the calling agent is grounded in (rt.GROUNDING)."""
    if "ontology.ask" in rt.TOOLS:
        return

    def current():
        g = rt.GROUNDING.get()
        if not g or g["ontology"] not in REGISTRY:
            raise OntologyError("this agent is not grounded in an ontology (add `grounded in <Ontology>`)")
        return g, REGISTRY[g["ontology"]]

    def _ask(q):
        """Answer a data question from certified ontology definitions (returns the SQL and lineage)."""
        g, onto = current()
        a = ask(onto, str(q))
        g["answers"].append({k: a.get(k) for k in ("status", "question", "terms", "tables", "sql", "params",
                                                   "certified", "uncertified", "reason")})
        return render_answer(a)

    def _search(q):
        """Ontology terms that match a question, with their definitions and certification."""
        _g, onto = current()
        out = []
        for s, n in search(onto, str(q)):
            t = onto.terms[n]
            out.append(f"{n} ({'certified by ' + t['certified'] if t.get('certified') else 'not certified'}): "
                       f"{t.get('description', '')}" + (f" · measure {t['measure']}" if t.get("measure") else ""))
        return "\n".join(out) or "no matching terms"

    def _term(q):
        """One ontology term's full definition."""
        _g, onto = current()
        n = next((x for x in onto.terms if x.lower() == str(q).strip().lower()), None)
        return json.dumps(onto.terms.get(n), ensure_ascii=False) if n else f"no term named {q!r}"

    def _validate(q):
        """Check SQL against the ontology's certified definitions and declared joins."""
        _g, onto = current()
        v = validate_sql(onto, str(q))
        return "valid" if v["ok"] else "invalid: " + "; ".join(v["problems"] + [f"uncertified: {u}" for u in v["uncertified"]])

    for nm, fn in (("ontology.ask", _ask), ("ontology.search", _search), ("ontology.term", _term),
                   ("ontology.validate", _validate)):
        rt.register_tool(nm)(fn)


# ── command line ─────────────────────────────────────────────────────────────────────────────────────────────
def load_from_program(path, name=None):
    import algoc
    p = Path(path)
    prog, _ = algoc.load_program(p.read_text(encoding="utf-8"), p.name, p.resolve().parent)
    if not prog.ontologies:
        raise OntologyError(f"{p.name} declares no ontology")
    if name is None:
        if len(prog.ontologies) > 1:
            raise OntologyError(f"{p.name} declares several ontologies; choose one with --name "
                                f"({', '.join(prog.ontologies)})")
        name = next(iter(prog.ontologies))
    if name not in prog.ontologies:
        raise OntologyError(f"no ontology named {name} in {p.name}")
    d = prog.ontologies[name]
    return Ontology.from_dict(d, d.get("base") or p.resolve().parent)


def certify_source(path, term, by, on=None):
    """Write `certified "by" on "date"` into a term in the source file (the review shows up in the diff)."""
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    m = re.search(rf"(?m)^(\s*)term\s+{re.escape(term)}\b[^{{\n]*\{{", src)
    if not m:
        raise OntologyError(f"no term {term} in {p.name}")
    depth, i = 1, m.end()
    while depth and i < len(src):
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    body = src[m.end():i - 1]
    on = on or time.strftime("%Y-%m-%d")
    line = f'certified "{by}" on "{on}"'
    if re.search(r"\bcertified\b", body):
        body = re.sub(r'certified\s+"[^"]*"(\s+on\s+"[^"]*")?', line, body, count=1)
    elif "\n" in body:
        indent = m.group(1) + "    "
        body = body.rstrip() + f"\n{indent}{line}\n{m.group(1)}"
    else:
        body = f" {body.strip()}  {line} " if body.strip() else f" {line} "
    p.write_text(src[:m.end()] + body + src[i - 1:], encoding="utf-8")
    return on


def cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="algo onto", description="AlgoOnto™, ontology as code: discover, certify, check, "
                                                               "ask, validate, snapshot, drift, export, graph")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("discover", help="profile a database (SQLite file, duckdb:file, postgresql://…) and propose "
                                        "an ontology as AlgoLang source")
    s.add_argument("db")
    s.add_argument("--name")
    s.add_argument("--history", help="a file of past SQL queries; aggregates with aliases become proposed measures")
    s.add_argument("-o", "--out", help="write the source here (default: print it)")
    s = sub.add_parser("check", help="compare an ontology with its data: columns, joins, measures, certification")
    s.add_argument("file")
    s.add_argument("--name")
    s = sub.add_parser("certify", help="certify a term in the source: certified \"<by>\" on \"<date>\"")
    s.add_argument("file")
    s.add_argument("terms", nargs="+")
    s.add_argument("--by", required=True)
    s.add_argument("--on")
    s = sub.add_parser("ask", help="answer a question from certified definitions, with SQL and lineage")
    s.add_argument("file")
    s.add_argument("question")
    s.add_argument("--name")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("validate", help="check SQL against the ontology's definitions")
    s.add_argument("file")
    s.add_argument("sql")
    s.add_argument("--name")
    s = sub.add_parser("snapshot", help="record the data's current shape as the baseline for drift (v1.4)")
    s.add_argument("file")
    s.add_argument("--name")
    s.add_argument("-o", "--out")
    s = sub.add_parser("drift", help="compare the data with the snapshot: breaking changes, moved measures, new "
                                     "values, stale certifications (v1.4)")
    s.add_argument("file")
    s.add_argument("--name")
    s.add_argument("--snapshot")
    s.add_argument("--tolerance", type=float, default=0.25, help="relative change that counts as drift (0.25)")
    s.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("export", help="export as OWL/RDF (Turtle) or JSON-LD for other tools (v1.4)")
    s.add_argument("file")
    s.add_argument("--name")
    s.add_argument("--format", choices=["ttl", "owl", "jsonld"], default="ttl", help="ttl/owl: Turtle; jsonld")
    s.add_argument("--base", help="IRI base for terms (default urn:algolang:onto:<Name>#)")
    s.add_argument("-o", "--out")
    s = sub.add_parser("graph", help="draw the ontology: entities, terms, measures, joins, certification (v1.4)")
    s.add_argument("file")
    s.add_argument("--name")
    s.add_argument("--html", help="write a web page (default: print SVG)")
    s = sub.add_parser("terms", help="list terms with their mappings and certification")
    s.add_argument("file")
    s.add_argument("--name")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "discover":
            onto, notes, rels = discover(a.db, a.name, a.history)
            src = to_source(onto, notes, rels)
            if a.out:
                Path(a.out).write_text(src, encoding="utf-8")
                print(f"✓ ontology {onto.name}: {len(onto.terms)} terms, {len(onto.relations)} relations, "
                      f"{sum(1 for t in onto.terms.values() if t.get('measure'))} measures → {a.out}")
                print(f"  {DIM}nothing is certified yet: review, then `algo onto certify {a.out} <Term> --by <you>`{END}")
            else:
                print(src, end="")
            return 0
        if a.cmd == "certify":
            for t in a.terms:
                on = certify_source(a.file, t, a.by, a.on)
                print(f"✓ {t} certified by {a.by} on {on}")
            return 0
        onto = load_from_program(a.file, a.name)
        if a.cmd == "check":
            probs = onto.check()
            errs = [m for s_, m in probs if s_ == "error"]
            print(f"{BOLD}AlgoOnto™ · {onto.name}{END}  {DIM}{re.sub(r'//[^@/]*@', '//', onto.source or '')} · {len(onto.terms)} terms · "
                  f"{len(onto.relations)} relations · {sum(1 for t in onto.terms if onto.certified(t))} certified{END}")
            for sev, m in probs:
                col = RED if sev == "error" else GOLD if sev == "warning" else DIM
                print(f"  {col}{sev:<8}{END} {m}")
            if not probs:
                print(f"  {GREEN}✓ every column, join and measure matches the data, and every term is certified{END}")
            return 1 if errs else 0
        if a.cmd == "ask":
            ans = ask(onto, a.question)
            print(json.dumps(ans, indent=1, default=str, ensure_ascii=False) if a.json else render_answer(ans))
            return 0 if ans["status"] in ("answered", "uncertified") else 1
        if a.cmd == "validate":
            v = validate_sql(onto, a.sql)
            if v["ok"]:
                print(f"{GREEN}✓ valid{END}: uses {', '.join(v['terms']) or 'no terms'}, all certified")
                return 0
            for p in v["problems"]:
                print(f"  {RED}✗{END} {p}")
            for u in v["uncertified"]:
                print(f"  {GOLD}⚠{END} measure {u} is not certified")
            return 1
        if a.cmd == "export":
            text = json.dumps(to_jsonld(onto, a.base), indent=1, ensure_ascii=False) + "\n" if a.format == "jsonld" \
                else to_turtle(onto, a.base)
            if a.out:
                Path(a.out).write_text(text, encoding="utf-8")
                print(f"✓ {onto.name} → {a.out} ({'JSON-LD' if a.format == 'jsonld' else 'OWL/RDF Turtle'}, "
                      f"{len(to_triples(onto, a.base))} triples)")
            else:
                print(text, end="")
            return 0
        if a.cmd == "graph":
            if a.html:
                Path(a.html).write_text(graph_html([onto], f"AlgoOnto™ · {onto.name}"), encoding="utf-8")
                print(f"✓ graph of {onto.name} → {a.html}")
            else:
                print(graph_svg(onto))
            return 0
        if a.cmd == "snapshot":
            snap = snapshot(onto)
            out = Path(a.out) if a.out else snapshot_path(a.file, onto.name)
            out.write_text(json.dumps(snap, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"✓ snapshot of {onto.name}: {len(snap['tables'])} tables, {len(snap['values'])} value sets, "
                  f"{len(snap['measures'])} measures → {out}")
            return 0
        if a.cmd == "drift":
            sp = Path(a.snapshot) if a.snapshot else snapshot_path(a.file, onto.name)
            if not sp.exists():
                raise OntologyError(f"no snapshot at {sp}: take one first with `algo onto snapshot {a.file}`")
            found = drift(onto, json.loads(sp.read_text(encoding="utf-8")), a.tolerance)
            if a.json:
                print(json.dumps(found, indent=1, ensure_ascii=False))
            else:
                snap_when = json.loads(sp.read_text(encoding="utf-8")).get("taken", "?")
                print(f"{BOLD}AlgoOnto™ drift · {onto.name}{END}  {DIM}since snapshot {snap_when}{END}")
                for f in found:
                    col = RED if f["severity"] == "breaking" else GOLD if f["severity"] == "warning" else DIM
                    print(f"  {col}{f['severity']:<9}{END} {f['kind']:<15} {f['message']}")
                if not found:
                    print(f"  {GREEN}✓ no drift: the data still matches every definition{END}")
            bad = [f for f in found if f["severity"] == "breaking" or (a.strict and f["severity"] == "warning")]
            return 1 if bad else 0
        if a.cmd == "terms":
            for n, t in onto.terms.items():
                mark = f"{GREEN}✓ {t['certified']}{END}" if t.get("certified") else f"{DIM}not certified{END}"
                print(f"  {BOLD}{n:<20}{END} {', '.join(t['columns']):<34} {mark}"
                      + (f"  {DIM}{t['measure']}{END}" if t.get("measure") else ""))
            return 0
    except OntologyError as e:
        print(f"✗ {e}")
        return 2
    return 0
