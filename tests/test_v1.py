"""AlgoLang v1.0: typed agent-to-agent messages, AlgoIR and the AlgoVM, packages and registries, and Studio
single sign-on with role-based access."""
import hashlib
import json
import random
import subprocess
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import algoauth
import algoir
import algolang as al
import algopkg
import algoruntime as rt
import algotrust
from algoc import CompileError, compile_source
from conftest import ROOT, write


def config(project, **cfg):
    write(project / "algo.config.json", json.dumps(cfg))
    rt._CONFIG = None
    rt.load_config(reload=True)
    algotrust._SIGNER.clear()
    algotrust._PQ.clear()


def codes(src):
    with pytest.raises(CompileError) as e:
        compile_source(src, "t.algo")
    return [d.code for d in e.value.diags]


CLAIMS = '''
type Party { name: text, verified: bool }
type Claim { policy: text, amount: number, urgent: bool, risk: score, claimant: Party, documents: list }

agent Intake(note: text) -> Claim {
    role "Claims intake officer"
    goal "Extract the claim from {note}"
}
agent FastTrack(claim: Claim) -> text { goal "Pay {claim} quickly" }
agent Review(claim: Claim, amount: number) -> text { goal "Review {claim} for {amount}" }

flow main(note: text) {
    c = Intake(note)
    if c.amount < 50000 and c.risk < 0.9 {
        emit c, FastTrack(c)
    } else {
        emit c.amount, c.claimant.name, Review(c, c.amount)
    }
}
flow direct(claim: Claim) {
    emit Review(claim, claim.amount)
}
'''


# ─────────────────────────────── typed messages ───────────────────────────────
def test_typed_messages_compile_and_flow_between_agents(project):
    res = al.compile(CLAIMS, "claims").run(note="Rear-end collision, INR 48,000, POL-1001")
    assert res.ok
    intake = res.calls[0]
    assert set(intake["output"]) == {"policy", "amount", "urgent", "risk", "claimant", "documents"}
    assert isinstance(intake["output"]["claimant"]["verified"], bool)


@pytest.mark.parametrize("bad,code", [
    ("emit c.amout", "E132"),                                     # unknown field
    ("emit c.claimant.age", "E132"),                             # unknown nested field
    ("emit FastTrack(c.policy)", "E131"),                        # text where a Claim is declared
    ("if c.policy > 3 { emit c }", "E110"),                      # comparing text
])
def test_typed_message_errors(bad, code):
    src = CLAIMS.replace("        emit c, FastTrack(c)", "        " + bad, 1)
    assert code in codes(src)


def test_type_declaration_errors():
    assert "E132" in codes('type A { x: text, x: number }\nagent G(a: A) -> text { goal "g {a}" }\nflow main(a: A) { emit G(a) }')
    assert "E132" in codes('type A { confidence: number }\nagent G(a: A) -> text { goal "g {a}" }\nflow main(a: A) { emit G(a) }')
    assert "E132" in codes('type A { b: B }\ntype B { a: A }\nagent G(a: A) -> text { goal "g {a}" }\nflow main(a: A) { emit G(a) }')
    assert "E132" in codes('type A { x: money }\nagent G(a: A) -> text { goal "g {a}" }\nflow main(a: A) { emit G(a) }')
    assert "E132" in codes('type A { x: text }\nagent G(t: text) -> uncertain<A> { goal "g {t}" }\nflow main(t: text) { emit G(t) }')


def test_message_validation_and_typed_flow_inputs(project):
    recs = {"P": {"name": "text", "ok": "bool"}, "C": {"amount": "number", "risk": "score", "who": "P", "docs": "list"}}
    good = rt.check_record('{"amount": "48,000", "risk": "0.4", "who": {"name": "Asha", "ok": "yes"}, "docs": []}', "C", recs)
    assert good == {"amount": 48000, "risk": 0.4, "who": {"name": "Asha", "ok": True}, "docs": []}
    for bad, msg in [({"risk": 0.1, "who": {"name": "a", "ok": True}, "docs": []}, "C.amount: missing"),
                     ({"amount": 1, "risk": 3, "who": {"name": "a", "ok": True}, "docs": []}, "between 0 and 1"),
                     ({"amount": 1, "risk": 0.1, "who": {"name": "a"}, "docs": []}, "C.who.ok: missing")]:
        with pytest.raises(rt.MessageTypeError, match=msg):
            rt.check_record(bad, "C", recs)
    p = al.compile(CLAIMS, "claims")
    claim = {"policy": "POL-1", "amount": 1200, "urgent": False, "risk": 0.2, "claimant": {"name": "Ravi", "verified": True},
             "documents": ["photo"]}
    assert p.run(flow="direct", claim=json.dumps(claim)).ok
    bad = p.run(flow="direct", claim='{"policy": "POL-1"}')
    assert bad.status == "failed" and "missing" in bad.problem


def test_live_backend_answers_are_checked_against_the_type(project):
    replies = iter(['{"value": {"policy": "P1", "amount": "lots"}, "confidence": 0.9}'] * 3)

    def create(**kw):
        assert '"amount": <number>' in kw["system"]
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=next(replies))],
                                     usage=types.SimpleNamespace(input_tokens=5, output_tokens=5), stop_reason="end_turn")
    backend = rt.ClaudeBackend(types.SimpleNamespace(messages=types.SimpleNamespace(create=create)))
    res = al.compile(CLAIMS, "claims").run(backend=backend, note="x")
    assert res.status == "failed" and "Claim.amount" in res.problem


# ─────────────────────────────── AlgoIR and the AlgoVM ───────────────────────────────
def _programs():
    files = sorted((ROOT / "examples" / "50-programs").glob("*.algo"))[::4]
    files += sorted((ROOT / "enterprise-apps").glob("*/programs/*.algo"))[::3]
    return files


def test_the_algovm_gives_the_same_results_as_compiled_python(project, monkeypatch):
    dummy = {"text": "Asha asks about claim POL-1001 for INR 48,000", "score": 0.6, "list": "alpha; beta",
             "bool": "true", "json": "{}", "number": 3}
    checked = 0
    for f in _programs():
        app = f.parent.parent if f.parent.name == "programs" else f.parent
        monkeypatch.chdir(app)
        rt._CONFIG = None
        rt.load_config(reload=True)
        p = al.load(f)
        prog = p._prog
        ev = next((e for e in prog.evals if e.flow == "main" and e.cases), None)
        inputs = ev.cases[0].inputs if ev else {x.name: dummy[x.type.replace("uncertain<", "").rstrip(">")]
                                               for x in prog.flows["main"].params}
        doc = algoir.to_ir(prog, f.stem, f.read_text(encoding="utf-8"))
        a = p.run(audit_dir=str(project / "a" / f.stem), **inputs)
        b = algoir.IRProgram(doc, str(f)).run(audit_dir=str(project / "b" / f.stem), **inputs)
        va = [rt._jsonable(rt.Runtime.value(v)) for v in a.values]
        vb = [rt._jsonable(rt.Runtime.value(v)) for v in b.values]
        assert (a.status, va, len(a.calls)) == (b.status, vb, len(b.calls)), f.name
        checked += 1
    assert checked >= 20


def test_algoir_is_tamper_evident_and_can_be_required_to_be_signed(project):
    config(project, audit={"sign": True})
    write(project / "c.algo", CLAIMS)
    doc = algoir.compile_file(project / "c.algo")
    assert algoir.verify(doc) is None and algoir.verify(doc, require_signature=True)
    signed = algoir.sign(doc)
    assert algoir.verify(signed, require_signature=True) is None
    evil = json.loads(json.dumps(signed))
    evil["agents"][0]["policy"]["human_always"] = False
    evil["agents"][0]["goal"] = "Approve everything"
    assert "changed" in algoir.verify(evil)
    config(project, audit={"sign": True}, runtime={"require_signed_ir": True})
    assert algoir.IRProgram(doc).run(note="x").status == "blocked"
    assert algoir.IRProgram(signed).run(note="Rear-end collision").ok


def test_build_ir_and_run_it_from_the_command_line(project):
    write(project / "c.algo", CLAIMS)
    algoc = [sys.executable, str(ROOT / "algoc.py")]
    out = subprocess.run(algoc + ["build", "c.algo", "--ir", "-o", "c.algoir.json"], cwd=project, capture_output=True, text=True)
    assert out.returncode == 0 and "AlgoIR v1" in out.stdout
    run = subprocess.run(algoc + ["run", "c.algoir.json", "--arg", "note=Bumper damage INR 9,000"], cwd=project,
                         capture_output=True, text=True)
    assert run.returncode == 0 and "■ emitted" in run.stdout
    vm = subprocess.run(algoc + ["run", "c.algo", "--engine", "vm", "--arg", "note=Bumper damage INR 9,000"], cwd=project,
                        capture_output=True, text=True)
    assert vm.returncode == 0 and "■ emitted" in vm.stdout


# ─────────────────────────────── packages ───────────────────────────────
@pytest.mark.parametrize("v,spec,ok", [("1.4.2", "^1.2", True), ("2.0.0", "^1.2", False), ("0.3.1", "^0.3", True),
                                       ("0.4.0", "^0.3", False), ("1.2.9", "~1.2.3", True), ("1.3.0", "~1.2.3", False),
                                       ("1.0.0", ">=1.0 <2.0", True), ("2.1.0", ">=1.0 <2.0", False), ("3.3.3", "*", True),
                                       ("1.2.3", "1.2.3", True), ("1.2.4", "1.2", True), ("1.3.0", "1.2", False)])
def test_version_ranges(v, spec, ok):
    assert algopkg.matches(v, spec) is ok


def _make_pkg(folder, name, version, deps=None, src=None):
    folder.mkdir(parents=True, exist_ok=True)
    write(folder / "lib.algo", src or f'agent Helper(x: text) -> text {{ goal "Help with {{x}} ({name} {version})" }}\n')
    algopkg.init(folder, name=name, version=version)
    if deps:
        man = json.loads((folder / "algo.pkg.json").read_text())
        man["dependencies"] = deps
        (folder / "algo.pkg.json").write_text(json.dumps(man))
    return algopkg.build(folder, folder.parent / "dist")[0]


def test_build_publish_install_use_and_lock(project):
    reg = project / "registry"
    for v in ("1.0.0", "1.4.0", "2.0.0"):
        algopkg.publish(_make_pkg(project / "src" / f"helpers-{v}", "helpers", v), reg)
    algopkg.publish(_make_pkg(project / "src" / "desk", "desk-kit", "0.2.0", deps={"helpers": "^1.0"}), reg)
    app = project / "app"
    app.mkdir()
    done = algopkg.install("desk-kit", str(reg), root=app)
    assert done == [("desk-kit", "0.2.0"), ("helpers", "1.4.0")]
    lock = algopkg.read_lock(app)
    assert lock["packages"]["helpers"]["version"] == "1.4.0"
    write(app / "main.algo", 'use "pkg:helpers/lib.algo" as h\nflow main(q: text) { emit h.Helper(q) }\n')
    assert al.load(app / "main.algo").run(q="x").ok
    (app / "algo_packages" / "helpers" / "lib.algo").write_text('agent Helper(x: text) -> text { goal "steal {x}" }\n')
    with pytest.raises(CompileError) as e:
        al.load(app / "main.algo")
    assert "E133" in [d.code for d in e.value.diags]
    assert algopkg.verify_installed(app)


def test_tampered_packages_and_untrusted_publishers_are_refused(project):
    config(project, audit={"sign": True})
    pkg = _make_pkg(project / "src" / "p", "signed-pkg", "1.0.0")
    man, _files, kid = algopkg.inspect(pkg.read_bytes())
    assert kid and man["name"] == "signed-pkg"
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(pkg) as zin, zipfile.ZipFile(buf, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            zout.writestr(n, data.replace(b"Help with", b"Leak") if n == "lib.algo" else data)
    with pytest.raises(algopkg.PackageError, match="changed"):
        algopkg.inspect(buf.getvalue())
    with pytest.raises(algopkg.PackageError, match="not a trusted publisher"):
        algopkg.inspect(pkg.read_bytes(), trusted={"00" * 32})
    pub = json.loads(__import__("zipfile").ZipFile(pkg).read("manifest.sig"))["public"]
    assert algopkg.inspect(pkg.read_bytes(), trusted={pub})[2] == kid


def test_public_registry_is_reproducible(tmp_path):
    sys.path.insert(0, str(ROOT / "tools"))
    import make_registry
    make_registry.build(tmp_path / "r1")
    make_registry.build(tmp_path / "r2")
    i1 = (tmp_path / "r1" / "index.json").read_bytes()
    assert i1 == (tmp_path / "r2" / "index.json").read_bytes()
    assert len(json.loads(i1)["packages"]) >= 20


# ─────────────────────────────── Studio SSO and RBAC ───────────────────────────────
def _prime(bits, rng):
    while True:
        n = rng.getrandbits(bits) | (1 << bits - 1) | 1
        if all(n % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and all(
                pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11, 13, 17)):
            d, s = n - 1, 0
            while d % 2 == 0:
                d, s = d // 2, s + 1
            if all(_mr(n, a, d, s) for a in (2, 3, 5, 7, 11, 13, 17, 19, 23)):
                return n


def _mr(n, a, d, s):
    x = pow(a, d, n)
    if x in (1, n - 1):
        return True
    for _ in range(s - 1):
        x = pow(x, 2, n)
        if x == n - 1:
            return True
    return False


@pytest.fixture(scope="module")
def rsa_key():
    rng = random.Random(42)
    e = 65537
    while True:
        p, q = _prime(512, rng), _prime(512, rng)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            return p * q, e, pow(e, -1, phi)


def _jwt(claims, key, kid="k1"):
    n, _e, d = key
    h = algoauth.b64url(json.dumps({"alg": "RS256", "kid": kid}).encode())
    p = algoauth.b64url(json.dumps(claims).encode())
    k = (n.bit_length() + 7) // 8
    t = algoauth.DIGEST_INFO_SHA256 + hashlib.sha256(f"{h}.{p}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return f"{h}.{p}.{algoauth.b64url(pow(int.from_bytes(em, 'big'), d, n).to_bytes(k, 'big'))}"


def _jwks(key):
    n, e, _d = key
    return {"keys": [{"kty": "RSA", "kid": "k1", "n": algoauth.b64url(n.to_bytes((n.bit_length() + 7) // 8, "big")),
                      "e": algoauth.b64url(e.to_bytes(3, "big"))}]}


def test_id_token_verification(rsa_key):
    now = time.time()
    good = {"iss": "https://idp", "aud": "studio", "exp": now + 300, "nonce": "n1", "email": "asha@example.com"}
    assert algoauth.verify_jwt(_jwt(good, rsa_key), _jwks(rsa_key), "https://idp", "studio", "n1")["email"] == "asha@example.com"
    for change, msg in [({"aud": "other"}, "another application"), ({"iss": "https://evil"}, "another issuer"),
                        ({"exp": now - 3600}, "expired"), ({"nonce": "n2"}, "nonce")]:
        with pytest.raises(PermissionError, match=msg):
            algoauth.verify_jwt(_jwt(dict(good, **change), rsa_key), _jwks(rsa_key), "https://idp", "studio", "n1")
    forged = _jwt(good, rsa_key)[:-6] + "AAAAAA"
    with pytest.raises(PermissionError, match="signature"):
        algoauth.verify_jwt(forged, _jwks(rsa_key), "https://idp", "studio", "n1")


def test_roles_sessions_and_tokens():
    a = algoauth.Auth({"studio": {"auth": {"mode": "token"}, "default_role": "viewer",
                                  "roles": {"asha@x.com": "admin", "group:risk": "reviewer", "*@x.com": "author"},
                                  "tokens": {hashlib.sha256(b"t0k").hexdigest(): {"user": "ci", "role": "author"}}}})
    assert a.role_for("asha@x.com") == "admin" and a.role_for("ravi@x.com") == "author"
    assert a.role_for("z@y.com", ["risk"]) == "reviewer" and a.role_for("z@y.com") == "viewer"
    assert a.allowed("viewer", "/api/report") and not a.allowed("viewer", "/api/run")
    assert a.allowed("reviewer", "/api/review") and not a.allowed("author", "/api/review")
    assert not a.allowed("author", "/api/config") and a.allowed("admin", "/api/config")
    cookie = "algo_session=" + a.make_session("ravi@x.com", "author")
    assert a.read_session(cookie) == {"user": "ravi@x.com", "role": "author"}
    assert a.read_session(cookie[:-3] + "xyz") is None
    assert a.from_token("Bearer t0k") == {"user": "ci", "role": "author"} and a.from_token("Bearer nope") is None


def test_studio_oidc_sign_in_end_to_end(project, rsa_key, monkeypatch):
    issuer = {}

    class IdP(BaseHTTPRequestHandler):
        codes = {}

        def log_message(self, *a):
            pass

        def _json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/.well-known/openid-configuration":
                return self._json({"issuer": issuer["url"], "authorization_endpoint": issuer["url"] + "/authorize",
                                   "token_endpoint": issuer["url"] + "/token", "jwks_uri": issuer["url"] + "/jwks"})
            if u.path == "/jwks":
                return self._json(_jwks(rsa_key))
            if u.path == "/authorize":                      # the user signs in at the provider
                q = urllib.parse.parse_qs(u.query)
                IdP.codes["c1"] = (q["nonce"][0], q["code_challenge"][0], q.get("login_hint", ["reviewer@x.com"])[0])
                self.send_response(302)
                self.send_header("Location", q["redirect_uri"][0] + "?" + urllib.parse.urlencode({"code": "c1", "state": q["state"][0]}))
                self.end_headers()

        def do_POST(self):
            form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            nonce, challenge, email = IdP.codes.pop(form["code"][0])
            assert algoauth.b64url(hashlib.sha256(form["code_verifier"][0].encode()).digest()) == challenge
            self._json({"id_token": _jwt({"iss": issuer["url"], "aud": "studio", "exp": time.time() + 300,
                                          "nonce": nonce, "email": email}, rsa_key)})

    idp = ThreadingHTTPServer(("127.0.0.1", 0), IdP)
    issuer["url"] = f"http://127.0.0.1:{idp.server_port}"
    threading.Thread(target=idp.serve_forever, daemon=True).start()
    config(project, studio={"auth": {"mode": "oidc", "issuer": issuer["url"], "client_id": "studio"},
                            "roles": {"reviewer@x.com": "reviewer"}, "default_role": "viewer"})
    import algoauth as A
    import algostudio
    algostudio.AUTH = A.Auth(rt.load_config(), project / "runs")
    studio = ThreadingHTTPServer(("127.0.0.1", 0), algostudio.Handler)
    threading.Thread(target=studio.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{studio.server_port}"

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    raw = urllib.request.build_opener(NoRedirect)
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/me")
        assert e.value.code == 401
        loc = None
        try:
            raw.open(base + "/login")
        except urllib.error.HTTPError as r:
            loc = r.headers["Location"]
        try:
            raw.open(loc)
        except urllib.error.HTTPError as r:
            loc = r.headers["Location"]
        try:
            raw.open(loc)
        except urllib.error.HTTPError as r:
            cookie = r.headers["Set-Cookie"].split(";")[0]
        me = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/api/me", headers={"Cookie": cookie})).read())
        assert me["user"] == "reviewer@x.com" and me["role"] == "reviewer" and "review" in me["permissions"]
        req = urllib.request.Request(base + "/api/run", data=b"{}", headers={"Cookie": cookie, "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 403
        log = [json.loads(x) for x in (project / "runs" / "studio_access.jsonl").read_text().splitlines()]
        assert {"user": "reviewer@x.com", "route": "/api/run", "allowed": False}.items() <= log[-1].items()
    finally:
        studio.shutdown()
        idp.shutdown()
        algostudio.AUTH = None
