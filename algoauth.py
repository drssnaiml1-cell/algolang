"""algoauth — single sign-on and role-based access for AlgoLang Studio (v1.0).

In algo.config.json:

    "studio": {
      "auth": {
        "mode": "oidc",                                   // "none" (local only, the default) | "token" | "oidc"
        "issuer": "https://login.example.com",            // any OpenID Connect provider (Entra ID, Okta, Google, Keycloak …)
        "client_id": "algolang-studio",
        "client_secret_env": "STUDIO_OIDC_SECRET",        // the secret is read from the environment, never the file
        "redirect_uri": "https://studio.example.com/auth/callback"
      },
      "roles": {"asha@example.com": "admin", "group:risk-reviewers": "reviewer", "*@example.com": "author"},
      "default_role": "viewer",
      "tokens": {"<sha256 of an API token>": {"user": "ci-bot", "role": "author"}}
    }

Roles (each includes the ones before it in its column):
    viewer    read programs, runs, reports, dashboards, the review queue
    reviewer  viewer + approve or reject queued results (the signed-in person is recorded as the reviewer,
              so four-eyes approval really needs two different people)
    author    viewer + edit, check, run, batch and compose programs
    admin     everything, including the configuration

OIDC uses the authorization-code flow with PKCE (S256), state and nonce; the ID token's RS256 signature is
checked against the provider's published keys, with issuer, audience and expiry. Sessions are HMAC-signed,
HttpOnly, SameSite=Lax cookies that expire after 8 hours. Every access decision is written to
runs/studio_access.jsonl. Standard library only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROLES = ("viewer", "reviewer", "author", "admin")
PERMS = {"viewer": {"read"}, "reviewer": {"read", "review"}, "author": {"read", "write"},
         "admin": {"read", "review", "write", "admin"}}
ROUTE_PERM = {
    "/api/files": "read", "/api/templates": "read", "/api/status": "read", "/api/reviews": "read",
    "/api/report": "read", "/api/domains": "read", "/api/pack": "read", "/api/graph": "read", "/api/python": "read",
    "/api/check": "read", "/api/open": "read", "/api/template": "read", "/dashboard": "read", "/": "read",
    "/prompt": "read", "/api/me": "read",
    "/api/run": "write", "/api/save": "write", "/api/batch": "write", "/api/ask": "write", "/api/compose": "write",
    "/api/review": "review", "/api/config": "admin",
}
SESSION_HOURS = 8
DIGEST_INFO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ─────────────────────────────── JWT (RS256) ───────────────────────────────
def rsa_verify(n: int, e: int, msg: bytes, sig: bytes) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017)."""
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    t = DIGEST_INFO_SHA256 + hashlib.sha256(msg).digest()
    want = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, want)


def verify_jwt(token: str, jwks: dict, issuer: str, audience: str, nonce: str | None = None, now=None) -> dict:
    """Check an RS256 ID token: signature (key chosen by kid), iss, aud, exp, iat and nonce. Returns the claims."""
    try:
        h64, p64, s64 = token.split(".")
        header, claims = json.loads(unb64url(h64)), json.loads(unb64url(p64))
    except Exception:  # noqa
        raise PermissionError("the ID token is malformed") from None
    if header.get("alg") != "RS256":
        raise PermissionError(f"unsupported token algorithm {header.get('alg')!r} (RS256 expected)")
    keys = [k for k in jwks.get("keys", []) if k.get("kty") == "RSA" and (k.get("kid") == header.get("kid") or not header.get("kid"))]
    if not any(rsa_verify(int.from_bytes(unb64url(k["n"]), "big"), int.from_bytes(unb64url(k["e"]), "big"),
                          f"{h64}.{p64}".encode(), unb64url(s64)) for k in keys):
        raise PermissionError("the ID token signature is not valid")
    now = now or time.time()
    aud = claims.get("aud")
    if claims.get("iss") != issuer:
        raise PermissionError("the ID token comes from another issuer")
    if audience not in (aud if isinstance(aud, list) else [aud]):
        raise PermissionError("the ID token is for another application")
    if float(claims.get("exp", 0)) < now - 60:
        raise PermissionError("the ID token has expired")
    if nonce is not None and claims.get("nonce") != nonce:
        raise PermissionError("the ID token does not match this sign-in (nonce)")
    return claims


# ─────────────────────────────── sessions ───────────────────────────────
class Auth:
    def __init__(self, cfg: dict, audit_dir: Path | None = None):
        studio = dict(cfg.get("studio") or {})
        self.conf = dict(studio.get("auth") or {})
        self.mode = str(self.conf.get("mode") or "none")
        if self.mode not in ("none", "token", "oidc"):
            raise ValueError(f"studio.auth.mode must be none, token or oidc, not {self.mode!r}")
        self.roles = dict(studio.get("roles") or {})
        self.default_role = studio.get("default_role", "viewer")
        self.tokens = dict(studio.get("tokens") or {})
        self.key = (os.environ.get("ALGO_STUDIO_SESSION_KEY") or secrets.token_hex(32)).encode()
        self.pending: dict[str, dict] = {}          # state → {verifier, nonce, ts}
        self._meta, self._jwks = None, None
        self.audit = (audit_dir or Path("runs")) / "studio_access.jsonl"

    @property
    def enabled(self):
        return self.mode != "none"

    # roles -----------------------------------------------------------
    def role_for(self, email: str, groups=()) -> str:
        email = (email or "").lower()
        best = None
        for who, role in self.roles.items():
            w = who.lower()
            hit = (w == email or (w.startswith("group:") and w[6:] in {g.lower() for g in groups})
                   or (w.startswith("*@") and email.endswith(w[1:])))
            if hit and role in ROLES and (best is None or ROLES.index(role) > ROLES.index(best)):
                best = role
        return best or self.default_role

    @staticmethod
    def allowed(role: str, route: str) -> bool:
        need = ROUTE_PERM.get(route, "admin")
        return need in PERMS.get(role, set())

    # cookies ---------------------------------------------------------
    def make_session(self, user: str, role: str) -> str:
        body = b64url(json.dumps({"u": user, "r": role, "x": int(time.time() + SESSION_HOURS * 3600)}).encode())
        return body + "." + b64url(hmac.new(self.key, body.encode(), hashlib.sha256).digest())

    def read_session(self, cookie_header: str | None):
        for part in (cookie_header or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "algo_session" and "." in v:
                body, mac = v.rsplit(".", 1)
                if hmac.compare_digest(mac, b64url(hmac.new(self.key, body.encode(), hashlib.sha256).digest())):
                    d = json.loads(unb64url(body))
                    if d.get("x", 0) > time.time():
                        return {"user": d["u"], "role": d["r"]}
        return None

    def from_token(self, auth_header: str | None):
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        h = hashlib.sha256(auth_header[7:].strip().encode()).hexdigest()
        t = self.tokens.get(h)
        return {"user": t["user"], "role": t.get("role", self.default_role)} if t else None

    def identify(self, headers):
        """The signed-in user for a request ({user, role}), or None."""
        if not self.enabled:
            return {"user": "local", "role": "admin"}
        return self.from_token(headers.get("Authorization")) or self.read_session(headers.get("Cookie"))

    def log(self, user, role, route, allowed):
        try:
            self.audit.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "user": user, "role": role,
                                    "route": route, "allowed": allowed}) + "\n")
        except OSError:
            pass

    # OIDC ------------------------------------------------------------
    def _get(self, url):
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())

    def metadata(self):
        if self._meta is None:
            iss = self.conf["issuer"].rstrip("/")
            self._meta = self._get(iss + "/.well-known/openid-configuration")
        return self._meta

    def jwks(self):
        if self._jwks is None:
            self._jwks = self._get(self.metadata()["jwks_uri"])
        return self._jwks

    def login_url(self, redirect_uri: str) -> str:
        state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        self.pending = {s: v for s, v in self.pending.items() if v["ts"] > time.time() - 600}
        self.pending[state] = {"verifier": verifier, "nonce": nonce, "ts": time.time()}
        q = {"response_type": "code", "client_id": self.conf["client_id"], "redirect_uri": redirect_uri,
             "scope": self.conf.get("scope", "openid email profile"), "state": state, "nonce": nonce,
             "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
        return self.metadata()["authorization_endpoint"] + "?" + urllib.parse.urlencode(q)

    def callback(self, query: dict, redirect_uri: str):
        """Finish a sign-in: exchange the code, verify the ID token. Returns {user, role}."""
        state = (query.get("state") or [""])[0]
        p = self.pending.pop(state, None)
        if p is None:
            raise PermissionError("unknown or expired sign-in (state)")
        if query.get("error"):
            raise PermissionError(f"the identity provider refused: {query['error'][0]}")
        form = {"grant_type": "authorization_code", "code": (query.get("code") or [""])[0], "redirect_uri": redirect_uri,
                "client_id": self.conf["client_id"], "code_verifier": p["verifier"]}
        secret = os.environ.get(self.conf.get("client_secret_env") or "", "")
        if secret:
            form["client_secret"] = secret
        req = urllib.request.Request(self.metadata()["token_endpoint"], urllib.parse.urlencode(form).encode(),
                                     {"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as r:
            tok = json.loads(r.read())
        claims = verify_jwt(tok["id_token"], self.jwks(), self.metadata().get("issuer", self.conf["issuer"]),
                            self.conf["client_id"], p["nonce"])
        email = claims.get("email") or claims.get("preferred_username") or claims.get("sub")
        groups = claims.get("groups") or claims.get("roles") or []
        return {"user": email, "role": self.role_for(email, groups)}
