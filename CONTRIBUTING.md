# Contributing to AlgoLang

Thank you for helping build an agent-native language that puts governance first.

- **Questions and ideas:** open a [Discussion](https://github.com/drssnaiml1-cell/algolang/discussions), or an issue with the *Feature request* template.
- **Bugs:** use the *Bug report* template and include `algo doctor` output and the smallest `.algo` file that shows the problem.
- **New domain packs:** use the *Domain pack proposal* template. Say who the users are, list the agents, give the risk level, and say what must never be automated.
- **Security problems:** do **not** open a public issue. See [SECURITY.md](SECURITY.md).

## Development in five commands

```bash
git clone https://github.com/drssnaiml1-cell/algolang && cd algolang
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
make check                                            # ruff + pytest + .algo lint
git checkout -b feature/my-change
```

[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) explains the architecture, and has step-by-step recipes for new syntax, error codes, tools, packs, Studio endpoints and CLI commands.

## Pull request checklist

- [ ] One logical change per PR, with tests (`tests/`), and docs where users will notice the change.
- [ ] `make check` passes locally.
- [ ] Governance is never weakened: org policy can only tighten, and every tool remains an explicit capability.
- [ ] Error messages say what is wrong *and* how to fix it.
- [ ] `CHANGELOG.md` has an entry under **Unreleased**.

By contributing you agree that your work is licensed under the [Apache License 2.0](LICENSE), and you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).
