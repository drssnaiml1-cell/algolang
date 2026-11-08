# AlgoLang for VS Code

Syntax highlighting for `.algo` files, plus the **AlgoLang language server** (`algo lsp`, new in v0.3):

- **Diagnostics as you type**: every compiler error (E100–E121), including organisation-policy checks from `algo.config.json`
- **Hover**: an agent's signature, role, goal, tools and policy; tools, models and keywords
- **Completion**: keywords, types, agents (including `alias.Agent` from packs), tools, models, domain packs after `use pack`, and snippets
- **Go to definition**: agents, flows and tools, including inside imported files and domain packs
- **Outline**: agents, flows, eval blocks and tools

## Install

```bash
pip install "algolang @ git+https://github.com/drssnaiml1-cell/algolang"   # provides `algo lsp`
cd vscode-algolang
npm install
npx @vscode/vsce package                # → algolang-0.3.0.vsix
code --install-extension algolang-0.3.0.vsix
```

If `algo` is not on your PATH, set **AlgoLang › Server: Command** to the full path, for example `D:\algolang\algo.bat` or `~/algolang/algo`.
Other editors (Neovim, Helix, Sublime) can start the same server with the command `algo lsp` over stdio.
