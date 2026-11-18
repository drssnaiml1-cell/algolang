# AlgoLang 1.3 examples: ontology as code

A governed context layer for data agents. The concept comes from NVIDIA's open-source
[Auto Ontology](https://github.com/NVIDIA/auto-ontology): agents need to know where data lives, what it means and
how to compute it before their numbers can be trusted. In AlgoLang the ontology is **source code**. It is declared
in the language, checked by the compiler, reviewed in pull requests and certified by name in the source.

| File | What it is |
|:--|:--|
| `make_retail_db.py` → `retail.db` | a small synthetic sales database (fixed seed): customers, products, orders, order lines |
| `query_history.sql` | past analyst queries; their named aggregates become proposed measures |
| `retail.onto.algo` | the ontology, **discovered** from `retail.db` and **certified** term by term |
| `sales_analyst.algo` | a data agent `grounded in Retail`, with evals |

```bash
# 1. Discover: profile the schema, infer joins, propose terms and measures (nothing is certified)
algo ontology discover examples/v13/retail.db --history examples/v13/query_history.sql -o retail.onto.algo

# 2. Certify: a person signs off each definition, in the source (it shows up in the pull request)
algo ontology certify retail.onto.algo NetRevenue Region OrderDate --by finance-data-team
algo ontology check retail.onto.algo            # columns, joins and measures against the data

# 3. Answer: certified definitions only, with SQL and lineage; never a guess
algo ontology ask examples/v13/retail.onto.algo "net revenue by region in 2025"
algo ontology ask examples/v13/retail.onto.algo "headcount by department"     # UNANSWERABLE
algo ontology validate examples/v13/retail.onto.algo "SELECT SUM(order_lines.amount*2) FROM order_lines"

# 4. Ground an agent in it, and serve the ontology to other agents over MCP
algo run examples/v13/sales_analyst.algo --arg "question=top 3 products by sales in 2025"
algo mcp serve examples/v13/sales_analyst.algo      # + retail_ask_question, retail_validate_sql, …
```

`DiscountGiven` (from query history) is deliberately left uncertified: answers that use it are flagged, and a
high-risk program grounded in this ontology would not compile until it is certified (E136).
