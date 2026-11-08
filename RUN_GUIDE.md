# How to run AlgoLang

AlgoLang needs only **Python 3.9 or newer**. Everything else is installed by the installer into a private `.venv` folder, so it never disturbs other Python projects.

## Three modes

After installing (Steps 1–3 below), choose the mode that suits you. Typing `algo` on its own opens a numbered menu with every option. All three modes use the same SDK (`import algolang`), so a program behaves the same everywhere.

| Mode | Start it with | Best for |
| --- | --- | --- |
| **Command line** | `algo` (menu) · `algo shell` · `algo chat` · `algo run` · `algo batch` | Scripts, batch jobs, CI, labs |
| **Graphical** | `algo studio` | Writing, running and governing programs in your browser |
| **Prompt-based UI** | `algo ui` (or `algo studio --prompt`) | Describing a problem in plain English and getting a governed solution |

**Command line: the shell.** `algo shell` lets you type AlgoLang one declaration at a time. Call an agent directly, such as `Explainer("neural networks")`, to run it at once. Useful commands: `:run topic=AI`, `:graph`, `:check`, `:save lesson.algo`, `:help`.

**Command line: prompt mode.** `algo chat` is the Prompt UI in your terminal. Type a problem. It finds the best domain pack, runs it, and shows every agent's result. Then:
- `1`, `2` or `3` switches to an alternative pack;
- `:show` prints the program;
- `:save` keeps a copy;
- `:ai` lets Claude customise it;
- `:live` turns real models on;
- `:quit` exits.

**Graphical: AlgoLang Studio.** `algo studio` opens an IDE in your browser: a highlighted editor, live error checking, ▶ Run (Ctrl+Enter), results, an agent diagram, the generated Python, templates and ✨ Ask AI. Three enterprise tabs sit alongside them:
- **Domains:** search the 120 packs by sector or in plain English, then *Open in editor* or *Use in my program*.
- **Batch:** upload or paste a CSV, run the program over every row in parallel, and download the results.
- **Governance:** usage tiles, usage per program, the human review queue (approve or reject) and the org policy.

Everything runs on your own computer at `127.0.0.1`.

**Prompt-based UI.** `algo ui` opens a chat-style page. Describe a problem, for example *"Triage this insurance claim: rear-end collision in Pune"*. AlgoLang picks the best of the 120 domain programs and runs it under your org policy. It then shows:
- the agent chain;
- governance badges (human review, fairness rules, budget);
- each agent's output and confidence;
- the program source.

From there you can try an alternative, *Open in Studio*, or *Customise with AI*.

**Agentic: AI writes the program.** `algo ask "build a team that reviews research papers"` has Claude write AlgoLang. The compiler checks it, and any errors go back to the AI to fix. This needs `ANTHROPIC_API_KEY`. `algo wizard` builds a program from six questions without AI.

## Step 1. Install Python (once)

- **Windows:** download from <https://www.python.org/downloads/>. During setup, tick **"Add python.exe to PATH"**.
- **macOS:** `brew install python`, or use the python.org installer.
- **Ubuntu / Linux:** `sudo apt install python3 python3-venv`.

## Step 2. Unzip AlgoLang

Unzip `AlgoLang_v0.3.zip` anywhere, for example `D:\algolang` on Windows or `~/algolang` on Linux/macOS.

## Step 3. Run the installer (once)

| System | What to do |
| --- | --- |
| Windows | Double-click **`install.bat`**, or in Command Prompt: `cd D:\algolang` then `install.bat` |
| Linux / macOS | `cd ~/algolang` then `bash install.sh` |

The installer creates `.venv`, installs the parser, and finishes with `algo doctor`. You should see:

```
AlgoLang 0.3.0 environment check
  ✓ Python                 3.12.x
  ✓ lark (parser)          1.3.1
  • anthropic (live mode)  not installed — optional
  • ANTHROPIC_API_KEY      not set — optional
  ✓ runtime                ...
  ✓ compiler self-test     examples/research_brief.algo compiles
Ready.
```

A ✓ means it works. A • is optional and only needed for live mode (Step 5).

## Step 4. Run programs

Open a terminal **inside the algolang folder**. On Windows, type `algo` (it runs `algo.bat`). On Linux/macOS, type `./algo`, or just `algo` after a new terminal.

```bash
algo run examples/research_brief.algo --arg "topic=Blockchain data integrity"
algo run examples/paper_review.algo   --arg "paper=LG-CEF for diabetic retinopathy grading"
algo check examples/bad_example.algo
```

### Write your own program

```bash
algo new mylesson
algo run mylesson.algo --arg "topic=Neural networks"
```

`algo new` creates a ready-to-run starter with three agents. Edit it in any text editor.

### All commands

| Command | What it does |
| --- | --- |
| `algo doctor` | Checks the environment is ready |
| `algo new NAME` | Creates `NAME.algo` from a starter template |
| `algo check FILE.algo` | Finds errors; generates nothing |
| `algo build FILE.algo` | Compiles to Python in `build/` next to the file |
| `algo run FILE.algo --arg "name=value"` | Compiles and runs `flow main` |
| `algo run ... --interactive` | Asks you to approve low-confidence results |
| `algo run ... --live` | Uses real Claude models instead of offline test agents |
| `algo run ... --audit-dir DIR` | Where audit logs are written (default `runs/`) |

If you leave out `--arg`, `algo run` asks for each input.

Every run writes an audit log to `runs/<program>.audit.jsonl`, one line per agent call.

## Step 4b. Enterprise projects

```bash
algo init acme          # creates the project below
cd acme
```

```
acme/
  algo.config.json            org policy, used by every program run here
  plugins/company_tools.py    your own tool: company.directory
  kb/policies.md              knowledge base searched by the kb.search tool
  programs/claims_ops.algo    a program that combines two domain packs with `use pack`
  data/claims.csv             sample records for batch runs
```

**`algo.config.json`**: the stricter of this file and a program's own policy always wins.

| Key | Meaning |
| --- | --- |
| `forbid` | Attributes no agent may receive (for example `caste`, `religion`, `salary`) |
| `max_budget_tokens` | The highest per-agent token budget any program may set |
| `min_human_below` | Every agent goes to human review below this confidence |
| `allowed_tools` | Only these tools may be declared (`null` = all) |
| `max_concurrency` | Global limit on simultaneous model calls |
| `max_run_tokens` | Token cap for one whole run |
| `cache` | `true` reuses identical answers at zero tokens |
| `models`, `tools`, `plugins` | Model aliases, tool settings, Python files that register tools |

**Enterprise commands**

| Command | What it does |
| --- | --- |
| `algo domains [words] [--sector S]` | Searches the 120 domain packs in plain English |
| `algo pack ID [--copy]` | Shows a pack's source; `--copy` saves it into your project to edit |
| `algo run pack:ID --arg "x=..."` | Runs a pack directly |
| `algo batch FILE --input data.csv [--workers 16] [--out results.csv]` | Runs a program over every CSV row in parallel |
| `algo review` · `algo review approve ID --reviewer NAME` · `algo review reject ID` | The human review queue |
| `algo audit verify [file-or-folder]` | Checks the hash chain of every audit log (detects edits and deletions) |
| `algo report [dir] [--json]` | Calls, tokens, escalations, blocks and confidence, per program |
| `algo chat` | Prompt mode in the terminal |

**Modules:** split big systems into files and reuse packs.

```algo
use "common/intake.algo" as intake
use pack insurance.fraud_screening as fraud

flow main(claim: text) {
    c     = intake.Normaliser(claim)
    views = par { fraud.PatternAnalyst(c), fraud.DocumentExaminer(c) }
    risk  = fraud.FraudPanel(views)
    emit c, risk
}
```

The full example is `examples/enterprise/claims_pipeline.algo`.

**Python SDK:** see `README.md`, or section 10 of the notebook.

## Step 4c. New in v0.3: uncertainty, evals, MCP, budgets, editor support

Try everything in the tour folder:

```bash
cd examples/v03
algo run expense_desk.algo --arg "claim=Conference fee USD 300, refunds policy question"
algo eval expense_desk.algo                 # run the eval block (offline) and record traces
algo eval expense_desk.algo --replay        # re-check from the traces: no model calls, zero cost
algo mcp list company-kb                    # the MCP server's tools
algo report                                 # tokens, money (USD and ₹), energy (Wh) and CO₂
```

| Command | What it does |
| --- | --- |
| `algo run FILE --trace` | Also save a trace of the run in `runs/traces/` |
| `algo replay TRACE` | Re-run a trace with no model calls; shows agents whose inputs changed (`--lenient` to continue past them) |
| `algo eval FILE [--live] [--replay [DIR]] [--record DIR] [--only NAME]` | Run the program's `eval` blocks |
| `algo mcp servers` · `algo mcp list SERVER` · `algo mcp call SERVER TOOL '{"arg": "x"}'` | Inspect and test MCP servers from `algo.config.json` |
| `algo lsp` | Language server for editors (started by the VS Code extension) |

**In programs:**

- `agent A(x: text) -> uncertain<score> { … policy { samples 5 } }` samples the agent five times. Use the result as `if a > 0.8 and a.confidence >= 0.7`.
- `policy { budget cost 0.05 usd  budget energy 2 wh }` sets per-agent budgets (`inr` and `kwh` also work).
- `tool kb.search_policies from mcp "company-kb"` binds a tool on an MCP server.
- `eval name on main { case "label" (x = "…") { expect called A  expect cost < 0.05 } }` adds behaviour tests next to the code.

**In `algo.config.json`:**

```json
"pricing": {"default": [3.0, 15.0]},
"usd_to_inr": 84.0,
"energy": {"wh_per_1k_tokens": {"default": 0.3}, "grid_kg_co2_per_kwh": 0.71},
"max_run_cost_usd": 0.50,
"max_run_energy_wh": 10,
"mcp_servers": {"company-kb": {"command": "{python}", "args": ["mcp_demo_server.py"]}}
```

`pricing` is USD per million input and output tokens. The defaults are placeholders, so set your contracted prices. `{python}` means the Python that runs AlgoLang.

## Step 4d. Real-time events with Kafka (v0.3.1)

A `stream` block runs a flow for every event on a Kafka topic. Try it offline first, with no Kafka needed:

```bash
cd enterprise-apps/algo-trading-desk
algo stream programs/pre_trade_check.algo --input data/order_events.jsonl
```

You will see each order routed to `orders.decisions`, `orders.review` (a person decides) or `orders.dlq` (unreadable event, blocked or failed run), plus latency and cost. Results are saved in `runs/streams/order_flow/`.

**With a real ZooKeeper + Kafka** (needs Docker):

```bash
pip install -r requirements-stream.txt                       # the Kafka client
docker compose -f deploy/kafka/docker-compose.yml up -d      # ZooKeeper, Kafka and the topics
cd enterprise-apps/algo-trading-desk
algo stream programs/pre_trade_check.algo --kafka --produce data/order_events.jsonl
algo stream programs/pre_trade_check.algo --kafka            # Ctrl+C to stop
docker compose -f ../../deploy/kafka/docker-compose.yml down # when you are done
```

| Option | What it does |
| --- | --- |
| `--input FILE` | Offline: read events from a JSON Lines file |
| `--kafka` | Use the cluster named in the stream block (address in `algo.config.json` → `kafka`) |
| `--produce FILE` | With `--kafka`: publish a JSON Lines file to the source topic, then exit |
| `--max N` · `--idle S` | Stop after N events, or after S seconds with no events |
| `--live` | Use real Claude models (default: the offline mock) |
| `--name S` | Choose a stream when a program has several |

Prefer Kafka without ZooKeeper? Use `deploy/kafka/docker-compose.kraft.yml` (KRaft mode, the default from Kafka 4.0). The commands are the same.

## Step 4e. Quantum tools (v0.3.2 preview)

Quantum tools need NumPy: `pip install -r requirements-quantum.txt` (or `pip install "algolang[quantum]"`).

```bash
cd enterprise-apps/quantum-optimization-lab
algo run programs/portfolio_optimizer.algo --arg "request=Choose 4 of the large-cap assets for a balanced growth mandate, risk aversion 0.5"
algo run programs/shift_scheduler.algo --arg "site=Visakhapatnam assembly plant, Monday"
algo eval programs/portfolio_optimizer.algo
```

The optimiser's answer starts with `VERIFIED` (it equals the exact classical optimum) or `GAP` (it does not, so the flow uses the classical answer). A request that needs more qubits than the policy allows comes back `BLOCKED`.

Use them in your own program:

```algo
tool quantum.maxcut
agent Split(graph: text) -> text {
    goal   "Split these jobs into two shifts: {graph}"
    uses   quantum.maxcut
    policy { shots 1024  max qubits 10 }
}
```

Organisation-wide limits go in `algo.config.json`: `"quantum": {"backend": "simulator", "max_qubits": 16, "shots": 2048, "seed": 11}`. To run `quantum.run` circuits on Qiskit Aer, `pip install qiskit qiskit-aer` and set `"backend": "qiskit-aer"`.

## Step 4f. Quantum circuits and applications (v0.3.3)

Write a circuit in AlgoLang, then run or export it:

```bash
cd enterprise-apps/quantum-optimization-lab
algo quantum run programs/circuit_lab.algo Bell          # about half 00, half 11: entanglement
algo quantum export programs/circuit_lab.algo --out qasm # OpenQASM 2.0 files for Qiskit or IBM Quantum
algo eval programs/circuit_lab.algo
```

The other three quantum applications:

```bash
cd ../soc-incident-command
algo run programs/pqc_readiness.algo --arg "scope=data/crypto_inventory.csv for the bank"
cd ../algo-trading-desk
algo run programs/risk_scenarios.algo --arg "book=data/risk_book.csv with correlation rho 0.35, limit 9000000"
cd ../supply-chain-control-tower
algo run programs/route_optimizer.algo --arg "request=data/route_options.csv, clash cost 60000 for shared lanes"
```

Settings in `algo.config.json`: `"quantum": {"qae_bits": 9}` (evaluation qubits for amplitude estimation) and `"pqc": {"quantum_threat_years": 10, "migration_years": 3}`. The years until a quantum computer can break today's public-key cryptography are an assumption: set your organisation's own.

## Step 5. Live mode with real Claude (optional)

By default agents are offline test agents, which give the same answer for the same input. To call real Claude models:

1. Get an API key from <https://console.anthropic.com>.
2. Install the SDK: run `install.bat --live` on Windows or `bash install.sh --live` on Linux/macOS.
3. Set the key in your terminal:
   - Windows Command Prompt: `set ANTHROPIC_API_KEY=sk-ant-...`
   - Windows PowerShell: `$env:ANTHROPIC_API_KEY="sk-ant-..."`
   - Linux / macOS: `export ANTHROPIC_API_KEY=sk-ant-...`
4. Run with `--live`:

```bash
algo run examples/research_brief.algo --arg "topic=Agentic AI in education" --live
```

Live calls cost API credits. Keep each agent's `budget tokens` policy set.

## Option: Jupyter Notebook or Google Colab

`AlgoLang_Notebook.ipynb` is a complete, self-contained notebook: lessons, examples, agent diagrams and results tables. You write AlgoLang in any cell that starts with `%%algo`.

**Google Colab (nothing to install):**

1. Open <https://colab.research.google.com>.
2. *File → Upload notebook* → choose `AlgoLang_Notebook.ipynb`.
3. *Runtime → Run all*.

**Jupyter on your computer:** after Step 3, run `algo notebook` in the algolang folder. It installs Jupyter the first time and opens the notebook in your browser.

**Cell options:**

| Cell first line | What it does |
| --- | --- |
| `%%algo --arg "topic=AI"` | Runs the program in the cell |
| `%%algo --define` | Adds the cell's agents to the session, so later cells can use them |
| `%%algo --graph ...` | Also draws the agent diagram |
| `%%algo --check` | Only checks for errors |
| `%%algo --python ...` | Also shows the generated Python |
| `%%algo --interactive ...` | Asks you to approve low-confidence results |
| `%%algo --live ...` | Uses real Claude (Colab: put `ANTHROPIC_API_KEY` in *Secrets*) |
| `%algo_run file.algo --arg "..."` | Runs an existing `.algo` file |
| `%algo_list` / `%algo_reset` | Shows or clears the session's definitions |

After each run, `algo_result` and `algo_calls` hold the results for normal Python cells.

## Option: VS Code

- **Language server (v0.3):** `vscode-algolang/` is a full extension that gives you live errors, hover, completion, go to definition and an outline through `algo lsp`. Build it with `cd vscode-algolang && npm install && npx @vscode/vsce package`, then install the `.vsix` file (see `vscode-algolang/README.md`).

- **Syntax colours:** copy the `vscode-algolang` folder into your VS Code extensions folder, then restart VS Code.
  - Windows: `%USERPROFILE%\.vscode\extensions\`
  - Linux / macOS: `~/.vscode/extensions/`
- **Run with a keypress:** open the algolang folder in VS Code, open any `.algo` file and press **Ctrl+Shift+B**. It asks for the input (for example `topic=AI ethics`) and runs. More tasks are under *Terminal → Run Task*: run live, and check.

## Option: Docker (same result on any machine)

```bash
docker build -t algolang .
docker run --rm -v "$PWD:/work" algolang run examples/research_brief.algo --arg "topic=AI ethics"
docker run --rm -e ANTHROPIC_API_KEY -v "$PWD:/work" algolang run examples/research_brief.algo --arg "topic=AI ethics" --live
```

## Troubleshooting

| Message | Fix |
| --- | --- |
| `'algo' is not recognized` (Windows) | Run it from inside the algolang folder, or add that folder to PATH (`install.bat` prints how) |
| `algo: command not found` (Linux/macOS) | Use `./algo`, or add `~/.local/bin` to PATH as the installer says |
| `Python 3.9 or newer is required` | Install Python (Step 1), then rerun the installer |
| `No module named 'lark'` | Rerun the installer, or `pip install lark` |
| `--live needs ANTHROPIC_API_KEY` | Set the key in the **same** terminal window (Step 5) |
| `--live needs the anthropic package` | Rerun the installer with `--live` |
| `✗ POLICY VIOLATION` | Not a bug: an agent's policy blocked the call (for example a forbidden attribute). Read the message |
| `PolicyViolation: tool ... not in allowed_tools` | Your org config does not allow that tool. Add it to `allowed_tools` |
| `audit chain broken at line N` | The audit log was edited or a line was deleted. Keep the file as evidence and investigate |
| `E1xx` errors | Compile errors with line numbers. See the specification's error table |
