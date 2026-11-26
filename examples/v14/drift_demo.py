"""AlgoOnto™ drift, end to end, on a throwaway copy of the v1.3 retail data.

    python examples/v14/drift_demo.py

1. copies examples/v13/retail.db and retail.onto.algo into a temporary folder
2. `algo onto snapshot` records the baseline the definitions were certified against
3. the data changes the way real data does: a column is renamed, a new region appears,
   amounts are restated (+50%) and a returns table is added
4. `algo onto drift` reports what broke, what moved and which certifications need review

The repository's own data is never changed. Exit status is drift's: 1 when something broke.
"""
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALGO = [sys.executable, str(ROOT / "algoc.py")]


def algo(*args):
    print(f"\n$ algo {' '.join(args)}")
    r = subprocess.run(ALGO + list(args), text=True, encoding="utf-8")
    return r.returncode


def main():
    with tempfile.TemporaryDirectory(prefix="algoonto-drift-") as tmp:
        tmp = Path(tmp)
        for f in ("retail.db", "retail.onto.algo"):
            shutil.copy(ROOT / "examples" / "v13" / f, tmp / f)
        onto = str(tmp / "retail.onto.algo")
        algo("onto", "snapshot", onto)
        print("\n… the data changes: products.category renamed, a 'Central' region, amounts restated, a returns table")
        con = sqlite3.connect(tmp / "retail.db")
        con.execute("ALTER TABLE products RENAME COLUMN category TO product_category")
        con.execute("INSERT INTO customers VALUES (121, 'New Co', 'Central', 'Retail')")
        con.execute("UPDATE order_lines SET amount = amount * 1.5")
        con.execute("CREATE TABLE returns (id INTEGER PRIMARY KEY, order_line_id INTEGER, amount REAL)")
        con.commit()
        con.close()
        return algo("onto", "drift", onto)


if __name__ == "__main__":
    sys.exit(main())
