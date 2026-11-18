"""Build retail.db, a small deterministic sales database for the v1.3 ontology examples.

    python examples/v13/make_retail_db.py            # writes examples/v13/retail.db

Synthetic data (fixed random seed): 120 customers in four regions, 24 products in four categories,
1,500 orders in 2024-2025 over three channels. orders.customer_id is a declared foreign key; the other joins
are left for `algo ontology discover` to infer from the data.
"""
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("retail.db")
out.unlink(missing_ok=True)
r = random.Random(7)
con = sqlite3.connect(out)
con.executescript("""
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, region TEXT, segment TEXT);
CREATE TABLE products  (id INTEGER PRIMARY KEY, name TEXT, category TEXT, unit_price REAL);
CREATE TABLE orders    (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
                        order_date TEXT, channel TEXT);
CREATE TABLE order_lines (id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER,
                          quantity INTEGER, amount REAL, discount REAL);
""")
regions = ["North", "South", "East", "West"]
segments = ["Retail", "Wholesale", "Online"]
first = ["Asha", "Ravi", "Meera", "Arjun", "Kavya", "Vikram", "Divya", "Rahul", "Sneha", "Kiran", "Priya", "Anil"]
last = ["Traders", "Stores", "Mart", "Enterprises", "Supplies"]
for i in range(1, 121):
    con.execute("INSERT INTO customers VALUES (?,?,?,?)",
                (i, f"{r.choice(first)} {r.choice(last)} {i}", regions[i % 4], r.choice(segments)))
cats = {"Electronics": (900, 4000), "Grocery": (40, 400), "Apparel": (300, 2500), "Home": (200, 3000)}
pid = 0
for cat, (lo, hi) in cats.items():
    for j in range(6):
        pid += 1
        con.execute("INSERT INTO products VALUES (?,?,?,?)", (pid, f"{cat} item {j + 1}", cat, round(r.uniform(lo, hi), 2)))
prices = dict(con.execute("SELECT id, unit_price FROM products"))
start, line = date(2024, 1, 1), 0
for o in range(1, 1501):
    d = start + timedelta(days=r.randrange(731))
    con.execute("INSERT INTO orders VALUES (?,?,?,?)", (o, r.randint(1, 120), d.isoformat(),
                                                       r.choice(["Store", "Online", "Partner"])))
    for _ in range(r.randint(1, 4)):
        line += 1
        p, q = r.randint(1, 24), r.randint(1, 6)
        disc = r.choice([0, 0, 0, 0.05, 0.1])
        con.execute("INSERT INTO order_lines VALUES (?,?,?,?,?,?)",
                    (line, o, p, q, round(prices[p] * q * (1 - disc), 2), disc))
con.commit()
con.close()
print(f"✓ {out} ({out.stat().st_size // 1024} KB)")
