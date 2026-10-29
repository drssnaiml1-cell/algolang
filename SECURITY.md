# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | ✅ |
| 0.1.x | ❌ please upgrade |

## Reporting a vulnerability

Please report privately. **Do not open a public issue.**

- Use GitHub's **[Report a vulnerability](https://github.com/drssnaiml1-cell/algolang/security/advisories/new)** (Security → Advisories), or
- email **ceo@algoprofessor.com** with the subject `AlgoLang security`.

Include the version (`algo doctor`), steps to reproduce, and the impact. We aim to acknowledge reports within 3 working days and to agree a fix and disclosure date with you.

## In scope

- Bypassing governance: a forbidden attribute reaching an agent, a tool used without being declared or allowed, org policy being relaxed by a program, or human review being skipped.
- Audit-log tampering that `algo audit verify` does not detect.
- Studio / Prompt UI: requests accepted from other origins or hosts, file access outside the workspace, or code execution from a web page.
- `file.read` or other built-in tools escaping their configured root.

## Good practice for deployments

- Keep `ANTHROPIC_API_KEY` in environment variables or a secret store, never in `.algo` files or `algo.config.json`.
- Studio binds to `127.0.0.1`. Do not expose it to a network without an authenticating reverse proxy.
- Treat plugin tools as production code: review them, and give them the least privilege they need.
- Store audit logs on write-once or backed-up storage, and run `algo audit verify` on a schedule.
