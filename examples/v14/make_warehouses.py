"""Copy the v1.3 retail database into DuckDB and/or PostgreSQL, for the AlgoOnto™ multi-database examples.

    python examples/v14/make_warehouses.py --duckdb examples/v14/retail.duckdb
    python examples/v14/make_warehouses.py --postgres postgresql://localhost/retail

Same tables, rows and keys as examples/v13/retail.db (synthetic data, fixed seed), with the same declared
foreign key (orders.customer_id), so discovery, questions and answers can be compared across engines.
"""
import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQLITE = HERE.parent / "v13" / "retail.db"
DDL = [
    "CREATE TABLE customers (id INTEGER PRIMARY KEY, name VARCHAR, region VARCHAR, segment VARCHAR)",
    "CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR, category VARCHAR, unit_price DOUBLE PRECISION)",
    "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), "
    "order_date DATE, channel VARCHAR)",
    "CREATE TABLE order_lines (id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, quantity INTEGER, "
    "amount DOUBLE PRECISION, discount DOUBLE PRECISION)",
]
TABLES = ["customers", "products", "orders", "order_lines"]


def rows():
    if not SQLITE.exists():
        subprocess.run([sys.executable, str(HERE.parent / "v13" / "make_retail_db.py")], check=True)
    con = sqlite3.connect(SQLITE)
    out = {t: con.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in TABLES}
    con.close()
    return out


def to_duckdb(path, data):
    import duckdb
    Path(path).unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    for ddl in DDL:
        con.execute(ddl.replace("DOUBLE PRECISION", "DOUBLE"))
    for t in TABLES:
        n = len(data[t][0])
        con.executemany(f"INSERT INTO {t} VALUES ({', '.join('?' * n)})", data[t])
    con.close()
    print(f"✓ {path}")


def to_postgres(dsn, data):
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as con:
        for t in reversed(TABLES):
            con.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        for ddl in DDL:
            con.execute(ddl)
        for t in TABLES:
            n = len(data[t][0])
            with con.cursor() as cur:
                cur.executemany(f"INSERT INTO {t} VALUES ({', '.join(['%s'] * n)})", data[t])
    print(f"✓ {dsn.split('@')[-1]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb")
    ap.add_argument("--postgres")
    a = ap.parse_args()
    data = rows()
    if a.duckdb:
        to_duckdb(a.duckdb, data)
    if a.postgres:
        to_postgres(a.postgres, data)
