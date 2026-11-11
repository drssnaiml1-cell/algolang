"""algopkg — AlgoLang packages and registries (v1.0 ecosystem).

    algo pkg init [DIR]                          write algo.pkg.json for the .algo files in a folder
    algo pkg build [DIR] [--out dist]            → dist/<name>-<version>.algopkg (zip; sha256 per file; signed)
    algo pkg publish FILE.algopkg --registry R   add it to a registry folder (index.json + packages)
    algo pkg search [TERM] [--registry R]        list packages in a registry
    algo pkg install NAME[@RANGE] [--registry R] download, verify, install into algo_packages/, update algo.lock
    algo pkg list | verify                       installed packages; re-check every file against algo.lock

In a program:   use "pkg:insurance/claims_triage.algo" as claims

A registry is a folder or a web address serving index.json and the package files (any static host works; the
public AlgoLang registry is published with the website). Version ranges: 1.2.0, ^1.2, ~1.2.3, >=1.0, *.

Supply-chain safety: every file is hashed in the package manifest; the manifest is signed with the publisher's
audit key (Ed25519, plus ML-DSA when configured); the registry index records each package's sha256; algo.lock
pins exact versions and hashes; the compiler refuses a `use "pkg:…"` file whose bytes no longer match the lock
(E133). With "registry": {"trusted_publishers": ["<Ed25519 public key hex>"]} only packages signed by those keys
can be installed.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

MANIFEST = "algo.pkg.json"
LOCK = "algo.lock"
PKG_DIR = "algo_packages"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)         # reproducible archives: the same inputs give the same bytes


class PackageError(Exception):
    pass


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ─────────────────────────────── versions ───────────────────────────────
def parse_version(v):
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(v).strip())
    if not m:
        raise PackageError(f"version '{v}' must look like 1.2.3")
    return tuple(int(x) for x in m.groups())


def matches(version, spec):
    """Does `version` satisfy `spec` (exact, ^, ~, >=, >, <=, <, *, or several joined by spaces)?"""
    v = parse_version(version)
    spec = (spec or "*").strip()
    if spec in ("*", "latest", ""):
        return True
    for part in spec.split():
        m = re.fullmatch(r"(\^|~|>=|<=|>|<|=)?(\d+)(?:\.(\d+))?(?:\.(\d+))?", part)
        if not m:
            raise PackageError(f"bad version range '{part}'")
        op, a, b, c = m.group(1) or "=", int(m.group(2)), m.group(3), m.group(4)
        base = (a, int(b or 0), int(c or 0))
        if op == "^":
            upper = (a + 1, 0, 0) if a > 0 else ((0, base[1] + 1, 0) if b is not None else (1, 0, 0))
            ok = base <= v < upper
        elif op == "~":
            ok = base <= v < ((a, base[1] + 1, 0) if b is not None else (a + 1, 0, 0))
        elif op == "=":
            ok = v[:1 + (b is not None) + (c is not None)] == base[:1 + (b is not None) + (c is not None)]
        else:
            ok = {">=": v >= base, "<=": v <= base, ">": v > base, "<": v < base}[op]
        if not ok:
            return False
    return True


# ─────────────────────────────── manifests and archives ───────────────────────────────
def init(folder=".", name=None, version="1.0.0", description=""):
    d = Path(folder)
    files = sorted(p.relative_to(d).as_posix() for p in d.rglob("*.algo") if PKG_DIR not in p.parts and "build" not in p.parts)
    if not files:
        raise PackageError(f"no .algo files in {d}")
    name = name or re.sub(r"[^a-z0-9-]", "-", d.resolve().name.lower()).strip("-")
    man = {"name": name, "version": version, "description": description or f"AlgoLang package {name}",
           "license": "Apache-2.0", "files": files, "dependencies": {}, "algolang": ">=1.0.0"}
    (d / MANIFEST).write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    return man


def _check_manifest(man):
    if not NAME_RE.match(str(man.get("name", ""))):
        raise PackageError("package name must be lowercase letters, digits and hyphens (2–64 characters)")
    parse_version(man.get("version", ""))
    if not man.get("files"):
        raise PackageError("the manifest lists no files")


def build(folder=".", out="dist"):
    """Build <name>-<version>.algopkg. Every program in it must compile; the manifest is hashed and signed."""
    import algoc
    d = Path(folder)
    man = json.loads((d / MANIFEST).read_text(encoding="utf-8"))
    _check_manifest(man)
    contents = {}
    for rel in man["files"]:
        p = d / rel
        if not p.is_file():
            raise PackageError(f"{rel} is listed in {MANIFEST} but does not exist")
        contents[rel] = p.read_bytes()
        if rel.endswith(".algo"):                 # every program must compile (libraries need no flow main)
            try:
                _prog, diags = algoc.load_program(contents[rel].decode("utf-8"), p.name, p.parent, library=True)
            except algoc.CompileError as e:
                diags = e.diags
            if diags:
                raise PackageError(f"{rel} does not compile: {diags[0]}")
    man = dict(man, sha256={k: _sha(v) for k, v in contents.items()})
    mbytes = json.dumps(man, indent=1, sort_keys=True).encode()
    sig = _sign(mbytes)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{man['name']}-{man['version']}.algopkg"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in [(MANIFEST, mbytes)] + ([("manifest.sig", json.dumps(sig).encode())] if sig else []) + \
                          sorted(contents.items()):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    target.write_bytes(buf.getvalue())
    return target, man


def _sign(mbytes):
    try:
        import algotrust
        s = algotrust.signer()
        if s is None:
            return None
        sig = {"kid": s[2], "public": s[1].hex(), "ed25519": algotrust.ed25519_sign(s[0], mbytes).hex()}
        pq = algotrust.pq_sign(mbytes)
        if pq:
            sig.update(palg=pq[0], pkid=pq[1], pqsig=pq[2], pq_public=algotrust.pq_signer()[1].hex())
        return sig
    except Exception:  # noqa
        return None


def inspect(data: bytes, trusted=None):
    """Open a package (bytes), check every hash and the signature. Returns (manifest, files, publisher kid)."""
    import algotrust
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        if MANIFEST not in names:
            raise PackageError("not an AlgoLang package (no algo.pkg.json)")
        mbytes = z.read(MANIFEST)
        man = json.loads(mbytes)
        _check_manifest(man)
        files = {}
        for rel, digest in (man.get("sha256") or {}).items():
            if rel not in names:
                raise PackageError(f"{rel} is missing from the package")
            b = z.read(rel)
            if _sha(b) != digest:
                raise PackageError(f"{rel} was changed after the package was built")
            files[rel] = b
        extra = names - set(files) - {MANIFEST, "manifest.sig"}
        if extra:
            raise PackageError(f"unexpected file(s) in the package: {', '.join(sorted(extra))}")
        kid = None
        if "manifest.sig" in names:
            sig = json.loads(z.read("manifest.sig"))
            pub = bytes.fromhex(sig["public"])
            if algotrust.key_id(pub) != sig["kid"] or not algotrust.ed25519_verify(pub, mbytes, bytes.fromhex(sig["ed25519"])):
                raise PackageError("the package signature is not valid")
            if "pqsig" in sig:
                ppub = bytes.fromhex(sig["pq_public"])
                if not algotrust.pq_verify(sig["palg"], ppub, mbytes, bytes.fromhex(sig["pqsig"])):
                    raise PackageError("the package's post-quantum signature is not valid")
            kid = sig["kid"]
            if trusted is not None and sig["public"] not in trusted:
                raise PackageError(f"signed by {kid}, which is not a trusted publisher (registry.trusted_publishers)")
        elif trusted is not None:
            raise PackageError("the package is not signed, and only trusted publishers are allowed")
    return man, files, kid


# ─────────────────────────────── registries ───────────────────────────────
def _registry(arg=None):
    if arg:
        return str(arg)
    try:
        import algoruntime as rt
        r = (rt.load_config().get("registry") or {}).get("url")
        if r:
            return r
    except Exception:  # noqa
        pass
    return "https://drssnaiml1-cell.github.io/algolang/registry"


def _trusted():
    try:
        import algoruntime as rt
        t = (rt.load_config().get("registry") or {}).get("trusted_publishers")
        return set(t) if t else None
    except Exception:  # noqa
        return None


def _fetch(registry, rel):
    if re.match(r"^https?://", registry):
        with urllib.request.urlopen(registry.rstrip("/") + "/" + rel, timeout=30) as r:
            return r.read()
    p = Path(registry) / rel
    if not p.exists():
        raise PackageError(f"{rel} not found in registry {registry}")
    return p.read_bytes()


def index(registry=None):
    reg = _registry(registry)
    try:
        return json.loads(_fetch(reg, "index.json"))
    except (OSError, PackageError) as e:
        raise PackageError(f"cannot read registry {reg}: {e}") from None


def publish(pkg_file, registry):
    reg = Path(registry)
    if re.match(r"^https?://", str(registry)):
        raise PackageError("publish to a registry folder (then host it on any static web server)")
    data = Path(pkg_file).read_bytes()
    man, _files, kid = inspect(data)
    reg.mkdir(parents=True, exist_ok=True)
    idx_path = reg / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {"registry": "AlgoLang package registry", "packages": {}}
    entry = idx["packages"].setdefault(man["name"], {"description": man.get("description", ""), "versions": {}})
    if man["version"] in entry["versions"] and entry["versions"][man["version"]]["sha256"] != _sha(data):
        raise PackageError(f"{man['name']} {man['version']} is already published with different contents; "
                           f"publish a new version")
    rel = f"packages/{man['name']}-{man['version']}.algopkg"
    (reg / "packages").mkdir(exist_ok=True)
    (reg / rel).write_bytes(data)
    entry["description"] = man.get("description", entry["description"])
    entry["versions"][man["version"]] = {"file": rel, "sha256": _sha(data), "publisher": kid,
                                         "dependencies": man.get("dependencies") or {}, "files": man["files"]}
    idx_path.write_text(json.dumps(idx, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return rel


def resolve(name, spec, idx):
    entry = (idx.get("packages") or {}).get(name)
    if entry is None:
        raise PackageError(f"no package named '{name}' in the registry")
    ok = [v for v in entry["versions"] if matches(v, spec)]
    if not ok:
        raise PackageError(f"{name}: no version matches '{spec}' (available: {', '.join(sorted(entry['versions']))})")
    best = max(ok, key=parse_version)
    return best, entry["versions"][best]


def _lock_path(root):
    return Path(root) / LOCK


def read_lock(root="."):
    p = _lock_path(root)
    return json.loads(p.read_text()) if p.exists() else {"lockfile": 1, "packages": {}}


def install(requirement, registry=None, root=".", _seen=None):
    """Install NAME[@RANGE] and its dependencies; returns the list of (name, version) installed."""
    name, _, spec = requirement.partition("@")
    reg = _registry(registry)
    idx = index(reg)
    _seen = _seen if _seen is not None else {}
    version, meta = resolve(name, spec or "*", idx)
    if name in _seen:
        if _seen[name] != version:
            raise PackageError(f"version conflict: {name} {version} and {_seen[name]} are both required")
        return []
    data = _fetch(reg, meta["file"])
    if _sha(data) != meta["sha256"]:
        raise PackageError(f"{name} {version}: the download does not match the registry's sha256")
    man, files, kid = inspect(data, _trusted())
    if man["name"] != name or man["version"] != version:
        raise PackageError(f"the registry entry {name} {version} contains {man['name']} {man['version']}")
    dest = Path(root) / PKG_DIR / name
    if dest.exists():
        for p in sorted(dest.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
    for rel, b in files.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_bytes(b)
    (dest / MANIFEST).write_text(json.dumps(man, indent=1, sort_keys=True), encoding="utf-8")
    lock = read_lock(root)
    lock["packages"][name] = {"version": version, "sha256": meta["sha256"], "publisher": kid, "registry": reg,
                              "files": {rel: _sha(b) for rel, b in files.items()}}
    _lock_path(root).write_text(json.dumps(lock, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    _seen[name] = version
    done = [(name, version)]
    for dep, dspec in (man.get("dependencies") or {}).items():
        done += install(f"{dep}@{dspec}", reg, root, _seen)
    return done


def verify_installed(root="."):
    """Re-hash every installed package file against algo.lock. Returns a list of problems (empty = intact)."""
    lock, problems = read_lock(root), []
    for name, meta in lock["packages"].items():
        for rel, digest in meta.get("files", {}).items():
            p = Path(root) / PKG_DIR / name / rel
            if not p.exists():
                problems.append(f"{name}: {rel} is missing")
            elif _sha(p.read_bytes()) != digest:
                problems.append(f"{name}: {rel} was changed after it was installed")
    return problems


def project_root(start: Path):
    """The folder holding algo.lock or algo_packages (searching upwards), else the start folder."""
    for d in [start, *start.parents]:
        if (d / LOCK).exists() or (d / PKG_DIR).is_dir():
            return d
    return start


def resolve_pkg_use(target: str, base_dir: Path):
    """`use "pkg:name/file.algo"` → (path or None, problem or None). Checked against algo.lock (E133)."""
    rest = target[4:]
    name, _, rel = rest.partition("/")
    root = project_root(base_dir.resolve())
    p = root / PKG_DIR / name / rel
    if not p.exists():
        return None, f'package file "{target}" is not installed (run: algo pkg install {name})'
    meta = read_lock(root)["packages"].get(name)
    if meta is None:
        return None, f"package {name} is not in {LOCK} (install it with algo pkg install {name})"
    want = (meta.get("files") or {}).get(rel)
    if want is None or _sha(p.read_bytes()) != want:
        return None, f'package file "{target}" does not match {LOCK}: it was changed after installation'
    return p.resolve(), None


# ─────────────────────────────── CLI ───────────────────────────────
def cli(action, args, registry=None, out="dist", name=None, version="1.0.0"):
    try:
        if action == "init":
            man = init(args[0] if args else ".", name=name, version=version)
            print(f"  ✓ {MANIFEST}: {man['name']} {man['version']} with {len(man['files'])} file(s)")
        elif action == "build":
            target, man = build(args[0] if args else ".", out)
            print(f"  ✓ built {target} ({len(man['files'])} file(s), sha256 {_sha(target.read_bytes())[:16]}…)")
        elif action == "publish":
            if not args or not registry:
                raise PackageError("usage: algo pkg publish FILE.algopkg --registry FOLDER")
            print(f"  ✓ published {publish(args[0], registry)} to {registry}")
        elif action == "search":
            idx = index(registry)
            term = (args[0] if args else "").lower()
            for n, e in sorted(idx.get("packages", {}).items()):
                if term in n or term in e.get("description", "").lower():
                    latest = max(e["versions"], key=parse_version)
                    print(f"  {n:<28} {latest:<8} {e.get('description', '')[:80]}")
        elif action == "install":
            if not args:
                raise PackageError("usage: algo pkg install NAME[@RANGE]")
            for req in args:
                for n, v in install(req, registry):
                    print(f"  ✓ installed {n} {v} → {PKG_DIR}/{n}")
        elif action == "list":
            for n, m in sorted(read_lock().get("packages", {}).items()):
                print(f"  {n:<28} {m['version']:<8} {len(m.get('files', {}))} file(s)  publisher {m.get('publisher') or 'unsigned'}")
        elif action == "verify":
            problems = verify_installed()
            for p in problems:
                print(f"  ✗ {p}")
            if not problems:
                print(f"  ✓ every installed package matches {LOCK}")
            return 1 if problems else 0
        return 0
    except PackageError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
