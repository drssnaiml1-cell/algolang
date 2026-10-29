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

Unzip `AlgoLang_v0.2.zip` anywhere, for example `D:\algolang` on Windows or `~/algolang` on Linux/macOS.

## Step 3. Run the installer (once)

| System | What to do |
| --- | --- |
| Windows | Double-click **`install.bat`**, or in Command Prompt: `cd D:\algolang` then `install.bat` |
| Linux / macOS | `cd ~/algolang` then `bash install.sh` |

The installer creates `.venv`, installs the parser, and finishes with `algo doctor`. You should see:

```
AlgoLang 0.2.0 environment check
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
