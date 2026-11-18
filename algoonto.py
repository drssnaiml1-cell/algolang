"""algoonto: ontology as code, a governed context layer for data agents (v1.3).

Inspired by NVIDIA's open-source Auto Ontology (github.com/NVIDIA/auto-ontology), which builds a context layer
so that agents know where enterprise data lives, what it means, and how to compute it. AlgoLang takes the same
idea one step further: the ontology is source code. It is declared in the language, checked by the compiler,
reviewed in pull requests, certified by name in the source, and enforced at run time.

    ontology Retail from "retail.db" {
        term Revenue "Net sales value of order lines" {
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

Three stages, as in Auto Ontology, all offline and deterministic:

    discover   algo ontology discover retail.db        profile the schema and propose terms, columns, joins and
                                                       measures (from data and query history) as AlgoLang source
    certify    algo ontology certify file.algo Revenue --by finance-team
                                                       a person signs off a definition, in the source
    answer     algo ontology ask file.algo "revenue by region in 2025"
                                                       retrieve terms, plan SQL from certified measures and declared
                                                       joins, validate it, run it read-only, return answer + lineage

Questions the definitions cannot support are reported as unanswerable, never guessed. Any SQL, from a person
or a model, can be checked against the ontology with `algo ontology validate`.
"""
from __future__ import annotations

import json
import re
import sqlite3
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
        p = Path(self.source)
        return p if p.is_absolute() else (self.base / p)

    def connect(self):
        p = self.db_path
        if p is None or not p.exists():
            raise OntologyError(f"ontology {self.name}: data source {self.source!r} not found")
        con = sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True, timeout=QUERY_SECONDS)
        start = time.monotonic()
        con.set_progress_handler(lambda: 1 if time.monotonic() - start > QUERY_SECONDS else 0, 10_000)
        return con

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
                con = self.connect()
            except OntologyError:
                return self._values
            with con:
                for n, t in self.terms.items():
                    for col in t.get("columns", []):
                        tb, c = col.split(".")
                        try:
                            rows = con.execute(f'SELECT DISTINCT "{c}" FROM "{tb}" WHERE typeof("{c}")=\'text\' '
                                               f'LIMIT 201').fetchall()
                        except sqlite3.Error:
                            continue
                        if 0 < len(rows) <= 200:
                            self._values[col] = [r[0] for r in rows if r[0] and len(str(r[0])) <= 60]
        return self._values

    # ── checking an ontology against its data ───────────────────────────────────────────────────────────────
    def check(self):
        """Problems found by comparing the declarations with the data source: list of (severity, message)."""
        out = []
        try:
            con = self.connect()
        except OntologyError as e:
            return [("error", str(e))]
        with con:
            schema = {t: {r[1] for r in con.execute(f'PRAGMA table_info("{t}")')}
                      for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            for n, t in self.terms.items():
                for col in t.get("columns", []):
                    tb, c = col.split(".")
                    if tb not in schema:
                        out.append(("error", f"term {n}: table '{tb}' does not exist"))
                    elif c not in schema[tb]:
                        out.append(("error", f"term {n}: column '{col}' does not exist"))
                if t.get("measure"):
                    v = validate_sql(self, f"SELECT {t['measure']} FROM {_from_for(self, t['measure'])}", certify=False)
                    out += [("error", f"term {n}: measure: {p}") for p in v["problems"]]
            for a, b in self.relations:
                ta, ca = a.split(".")
                tb, cb = b.split(".")
                if ta not in schema or ca not in schema.get(ta, ()) or tb not in schema or cb not in schema.get(tb, ()):
                    out.append(("error", f"relation {a} -> {b}: unknown table or column"))
                    continue
                orphans = con.execute(f'SELECT COUNT(*) FROM "{ta}" WHERE "{ca}" IS NOT NULL AND "{ca}" NOT IN '
                                      f'(SELECT "{cb}" FROM "{tb}")').fetchone()[0]
                if orphans:
                    out.append(("warning", f"relation {a} -> {b}: {orphans} row(s) in {ta} have no match in {tb}"))
            for n, t in self.terms.items():
                if not t.get("certified"):
                    out.append(("info", f"term {n} is not certified yet"))
        return out


def _from_for(onto, sql):
    tables = sorted(set(re.findall(r"\b([A-Za-z_]\w*)\.[A-Za-z_]\w*", sql)))
    return tables[0] if len(tables) == 1 else (", ".join(tables) or "sqlite_master")


# ── discovery ────────────────────────────────────────────────────────────────────────────────────────────────
def _camel(words):
    return "".join(w[:1].upper() + w[1:] for w in words if w)


def _a(phrase):
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


GENERIC = {"name", "code", "type", "status", "title", "label", "description", "date", "number", "no"}


def _singular(w):
    return w[:-3] + "y" if w.endswith("ies") else w[:-1] if w.endswith("s") and not w.endswith("ss") else w


def discover(db, name=None, history=None):
    """Profile a SQLite database and propose an ontology: one entity term per table (with a count measure), one
    term per meaningful column, joins from declared foreign keys and from verified value inclusion, and measures
    for amounts (SUM), rates (AVG) and aggregates found in query history. Nothing is certified."""
    db = Path(db)
    if not db.exists():
        raise OntologyError(f"no such database: {db}")
    con = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                        "ORDER BY name")]
    info, pk, rels = {}, {}, []
    for t in tables:
        cols = list(con.execute(f'PRAGMA table_info("{t}")'))
        info[t] = cols
        keys = [c[1] for c in cols if c[5]]
        pk[t] = keys[0] if len(keys) == 1 else None
        for fk in con.execute(f'PRAGMA foreign_key_list("{t}")'):
            rels.append((f"{t}.{fk[3]}", f"{fk[2]}.{fk[4] or 'id'}", "declared foreign key"))
    known = {(a, b) for a, b, _ in rels}
    for t in tables:                                          # inferred joins: x_id columns whose values ⊆ a key
        for c in info[t]:
            col = c[1]
            if col == pk[t] or not col.lower().endswith("_id"):
                continue
            stem = col[:-3].lower()
            for u in tables:
                if u == t or not pk[u] or _singular(u.lower()) != stem and u.lower() != stem:
                    continue
                if (f"{t}.{col}", f"{u}.{pk[u]}") in known:
                    continue
                n, orphans = con.execute(f'SELECT COUNT("{col}"), SUM("{col}" NOT IN (SELECT "{pk[u]}" FROM "{u}")) '
                                         f'FROM "{t}"').fetchone()
                if n and not orphans:
                    rels.append((f"{t}.{col}", f"{u}.{pk[u]}", f"inferred: every {t}.{col} value is a {u}.{pk[u]}"))
    fk_cols = {a for a, _, _ in rels}
    terms, notes = {}, {}
    for t in tables:
        rows = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        ent = _camel([_singular(w) for w in _words(t)])
        if pk[t]:
            ent_phrase = ' '.join(_singular(w) for w in _words(t))
            terms[ent] = dict(description=f"{_a(ent_phrase).capitalize()} ({t}, {rows:,} rows)",
                              synonyms=_syn([_singular(_words(t)[-1])]), columns=[f"{t}.{pk[t]}"],
                              measure=f"COUNT(DISTINCT {t}.{pk[t]})")
            notes[ent] = f"entity · {rows:,} rows"
        for c in info[t]:
            col, typ = c[1], (c[2] or "").upper()
            if col == pk[t] or f"{t}.{col}" in fk_cols:
                continue
            words = _words(col)
            tname = _camel(words)
            if set(words) <= GENERIC or tname in terms:
                tname = _camel([_singular(w) for w in _words(t)] + words)
            numeric = any(k in typ for k in ("INT", "REAL", "NUM", "DEC", "FLOA", "DOUB"))
            lo, hi, nd = con.execute(f'SELECT MIN("{col}"), MAX("{col}"), COUNT(DISTINCT "{col}") FROM "{t}"').fetchone()
            desc = f"{' '.join(words).capitalize()} of {_a(' '.join(_singular(w) for w in _words(t)))}"
            term = dict(description=desc, synonyms=_syn(words[-1:]), columns=[f"{t}.{col}"])
            if numeric and not any(w in ("year", "month", "day", "code", "zip", "pin") for w in words):
                ratio = lo is not None and hi is not None and 0 <= float(lo) and float(hi) <= 1 and "REAL" in typ
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
    con.close()
    used = {n.lower() for n in terms}                   # a word may name only one term (compile check E136)
    for n, t in terms.items():
        keep = []
        for sy in t.get("synonyms", []):
            if sy.lower() not in used and _camel(_words(sy)).lower() not in used:
                keep.append(sy)
                used.add(sy.lower())
        t["synonyms"] = keep
    name = name or _camel(_words(db.stem)) or "Data"
    return Ontology(name, db.name, terms, [(a, b) for a, b, _ in rels], db.parent), notes, rels


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
    L = [f"// Discovered by `algo ontology discover` from {onto.source}. Review every term, then certify it:",
         f"//   algo ontology certify <this file> <Term> --by <reviewer>", "",
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
        filters.append((f"strftime('%Y', {dcol})", "=", years[0]))
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
            con = onto.connect()
            with con:
                con.execute("EXPLAIN " + s, tuple(params))
                for col, val in re.findall(r"\b([A-Za-z_]\w*\.[A-Za-z_]\w*)\s*=\s*'([^']*)'", s):
                    tb, c = col.split(".")
                    if not con.execute(f'SELECT 1 FROM "{tb}" WHERE "{c}" = ? LIMIT 1', (val,)).fetchone():
                        problems.append(f"no row has {col} = '{val}'")
        except (sqlite3.Error, OntologyError) as e:
            problems.append(f"the database rejects the query: {e}")
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
    con = onto.connect()
    with con:
        cur = con.execute(p["sql"], tuple(p["params"]))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS)
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
    ap = argparse.ArgumentParser(prog="algo ontology", description="ontology as code: discover, check, certify, ask")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("discover", help="profile a SQLite database and propose an ontology as AlgoLang source")
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
                print(f"  {DIM}nothing is certified yet: review, then `algo ontology certify {a.out} <Term> --by <you>`{END}")
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
            print(f"{BOLD}ontology {onto.name}{END}  {DIM}{onto.source} · {len(onto.terms)} terms · "
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
