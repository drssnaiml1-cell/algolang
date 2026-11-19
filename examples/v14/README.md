# AlgoLang 1.4 examples: AlgoOnto™

**AlgoOnto™** is AlgoLang's ontology as code, a governed context layer for data agents, after the concept of
NVIDIA's open-source [Auto Ontology](https://github.com/NVIDIA/auto-ontology). Version 1.3 introduced it on SQLite;
1.4 brands it AlgoOnto™ and adds three engines, drift detection, standard exports and a graph view.
`algo onto …` and `algo ontology …` are the same command.

## One ontology, three engines

```bash
pip install "algolang[data]"                         # duckdb + psycopg (SQLite needs nothing)
python examples/v14/make_warehouses.py --duckdb examples/v14/retail.duckdb
python examples/v14/make_warehouses.py --postgres postgresql://localhost/retail

algo onto discover examples/v13/retail.db                      # SQLite file
algo onto discover duckdb:examples/v14/retail.duckdb            # DuckDB file
algo onto discover postgresql://analyst@localhost/retail        # PostgreSQL (password: PGPASSWORD)
```

Every engine is opened **read-only with a time limit** (SQLite `mode=ro`, DuckDB `read_only`, a PostgreSQL
read-only transaction with `statement_timeout`). Discovery writes `${PGPASSWORD}` instead of a password, and the
compiler rejects a password written into source (E136). The same questions give the same answers on all three.

## Drift: is the data still what was certified?

```bash
algo onto snapshot examples/v13/retail.onto.algo      # baseline → retail.onto.snapshot.json (review it with the ontology)
algo onto drift    examples/v13/retail.onto.algo      # exit 1 on breaking changes; --strict also on warnings
```

| Severity | Examples |
|:--|:--|
| breaking | a mapped column renamed or removed (with a "renamed?" hint), a type change, a measure that no longer runs |
| warning | a category gained or lost values (a new region), rows or a measure moved by more than `--tolerance` (25%) |
| info | new tables or columns the ontology does not cover yet |
| review | every certified term touched by a breaking change or a warning |

## Share it: OWL/RDF, JSON-LD and a picture

```bash
algo onto export examples/v13/retail.onto.algo -o retail.ttl                 # OWL/RDF (Turtle)
algo onto export examples/v13/retail.onto.algo --format jsonld -o retail.jsonld
algo onto graph  examples/v13/retail.onto.algo --html retail-graph.html      # also in Studio: ◈ AlgoOnto™
```

Entity terms become `owl:Class`, other terms `owl:DatatypeProperty`, joins `owl:ObjectProperty`, synonyms
`skos:altLabel`, descriptions `skos:definition`; columns, measures, joins and certification use the `algo:`
vocabulary. Both files describe the same graph.
