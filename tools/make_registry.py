"""Build the public AlgoLang package registry from the domain-pack library (v1.0).

One package per sector (packs/<sector>/*.algo), published into site/registry/ by the website build, so
`algo pkg install insurance` works against https://drssnaiml1-cell.github.io/algolang/registry.
Archives are reproducible: the same packs give byte-identical packages.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import algopkg  # noqa: E402
import algoruntime as rt  # noqa: E402

VERSION = rt.VERSION if rt.VERSION.count(".") == 2 else "1.0.0"


def build(out: Path):
    catalog = json.loads((ROOT / "packs" / "catalog.json").read_text(encoding="utf-8"))
    names = catalog.get("sectors") or {}
    if out.exists():
        shutil.rmtree(out)
    n = 0
    for sector in sorted(p for p in (ROOT / "packs").iterdir() if p.is_dir() and list(p.glob("*.algo"))):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / sector.name
            shutil.copytree(sector, d)
            name = sector.name.lower().replace("_", "-")
            man = algopkg.init(d, name=name, version=VERSION,
                               description=f"AlgoLang domain packs: {names.get(sector.name, sector.name)} "
                                           f"({len(list(sector.glob('*.algo')))} programs)")
            pkg, _ = algopkg.build(d, Path(tmp) / "dist")
            algopkg.publish(pkg, out)
            n += len(man["files"])
    print(f"registry → {out}: {len(json.loads((out / 'index.json').read_text())['packages'])} packages, {n} programs")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site" / "registry")
