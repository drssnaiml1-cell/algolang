# AlgoLang 1.4 examples: AlgoOnto™

**AlgoOnto™** is AlgoLang's ontology as code: a governed context layer that tells data agents where data lives,
what it means and how to compute it, after the concept of NVIDIA's open-source
[Auto Ontology](https://github.com/NVIDIA/auto-ontology). The ontology is source code: compiled, reviewed in pull
requests, certified by name and enforced at run time. `algo onto …` and `algo ontology …` are the same command.

| File | What it shows |
|:--|:--|
| [`make_warehouses.py`](make_warehouses.py) | copies the v1.3 retail data into **DuckDB** and/or **PostgreSQL** (same rows and keys) |
| [`retail_duckdb.onto.algo`](retail_duckdb.onto.algo) | ontology `RetailWarehouse`, **discovered from DuckDB** and certified term by term |
| [`retail_postgres.onto.algo`](retail_postgres.onto.algo) | ontology `RetailPostgres`, **discovered from PostgreSQL**; the password is `${PGPASSWORD}`, never written |
| [`warehouse_analyst.algo`](warehouse_analyst.algo) | a data agent `grounded in RetailWarehouse`, a narrator, and evals; refuses what the data cannot answer |
| [`drift_demo.py`](drift_demo.py) | snapshot → the data changes → `algo onto drift` reports what broke (on a throwaway copy) |
| [`exports/`](exports) | the v1.3 `Retail` ontology as OWL/RDF ([`retail.ttl`](exports/retail.ttl)), JSON-LD ([`retail.jsonld`](exports/retail.jsonld)) and a graph ([`retail-graph.html`](exports/retail-graph.html)) |
| [`../v13/retail.onto.snapshot.json`](../v13/retail.onto.snapshot.json) | the drift baseline of the v1.3 ontology (`algo onto drift examples/v13/retail.onto.algo` → no drift) |

## 1. One ontology, three engines

```bash
pip install "algolang[data]"                                       # duckdb + psycopg (SQLite needs nothing)
python examples/v14/make_warehouses.py --duckdb examples/v14/retail.duckdb
python examples/v14/make_warehouses.py --postgres postgresql://analyst:secret@localhost/retail   # optional

algo onto discover examples/v13/retail.db                          # SQLite file
algo onto discover duckdb:examples/v14/retail.duckdb               # DuckDB file
algo onto discover postgresql://analyst:secret@localhost/retail    # writes ${PGPASSWORD}, never "secret"
```

Every engine is opened **read-only with a time limit** (SQLite `mode=ro`, DuckDB `read_only`, a PostgreSQL read-only
transaction with `statement_timeout`). The same questions give the same answers on all three:

```bash
algo onto ask examples/v14/retail_duckdb.onto.algo "net revenue by region in 2025"
PGPASSWORD=secret algo onto ask examples/v14/retail_postgres.onto.algo "net revenue by region in 2025"
# Region: North · NetRevenue: 2,258,560.11   (both)
```

## 2. A grounded agent on the warehouse

```bash
algo run  examples/v14/warehouse_analyst.algo --arg "question=top 3 products by sales in 2025"
algo run  examples/v14/warehouse_analyst.algo --engine vm --arg "question=headcount by department"
algo eval examples/v14/warehouse_analyst.algo          # 2/2 cases pass
```

`WarehouseAnalyst` answers only from `RetailWarehouse`'s certified definitions; each answer's SQL and terms are in
the audit log. When a question is **UNANSWERABLE** (or the warehouse has not been built yet), the flow says so instead
of passing a guess to the narrator.

## 3. Drift: is the data still what was certified?

```bash
algo onto drift examples/v13/retail.onto.algo          # against the committed baseline: no drift
python examples/v14/drift_demo.py                      # a rename, a new region, restated amounts → exit 1
```

| Severity | Examples |
|:--|:--|
| breaking | a mapped column renamed or removed (with a "renamed?" hint), a type change, a measure that no longer runs |
| warning | a category gained or lost values (a new region), rows or a measure moved by more than `--tolerance` (25%) |
| info | new tables or columns the ontology does not cover yet |
| review | every certified term touched by a breaking change or a warning |

In CI: `algo onto drift my.onto.algo` exits 1 on breaking changes (`--strict` also on warnings).

## 4. Share it: OWL/RDF, JSON-LD and a picture

```bash
algo onto export examples/v13/retail.onto.algo -o retail.ttl                 # OWL/RDF (Turtle)
algo onto export examples/v13/retail.onto.algo --format jsonld -o retail.jsonld
algo onto graph  examples/v13/retail.onto.algo --html retail-graph.html      # also in Studio: ◈ AlgoOnto™
```

Entity terms become `owl:Class`, other terms `owl:DatatypeProperty`, joins `owl:ObjectProperty`, synonyms
`skos:altLabel`, descriptions `skos:definition`; columns, measures, joins and certification use the `algo:`
vocabulary. Both files describe the same graph (207 triples).
