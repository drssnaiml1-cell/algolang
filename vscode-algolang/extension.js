// AlgoLang for VS Code — starts `algo lsp` (the AlgoLang language server) for .algo files.
const vscode = require("vscode");
const { LanguageClient } = require("vscode-languageclient/node");

let client;

function activate(context) {
  const cfg = vscode.workspace.getConfiguration("algolang");
  if (!cfg.get("server.enabled", true)) return;
  const command = cfg.get("server.command", "algo");
  const args = cfg.get("server.args", ["lsp"]);
  const serverOptions = { command, args, options: { cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath } };
  const clientOptions = { documentSelector: [{ scheme: "file", language: "algolang" }] };
  client = new LanguageClient("algolang", "AlgoLang Language Server", serverOptions, clientOptions);
  client.start().catch((err) => {
    vscode.window.showWarningMessage(
      `AlgoLang: could not start "${command} ${args.join(" ")}" (${err.message}). ` +
      "Install AlgoLang (pip install algolang) or set algolang.server.command.");
  });
  context.subscriptions.push({ dispose: () => client && client.stop() });
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
