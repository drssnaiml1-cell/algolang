"""
algoagent — agentic programming for AlgoLang
AlgoProfessor AI R&D Solutions · AlgoLang v0.1

    algo ask "build a team that reviews research papers"     AI writes the program
    algo wizard                                              guided questions, no AI needed

`ask` uses Claude to write AlgoLang, compiles the result with the real compiler, and
sends any compile errors back to the model to repair — up to three attempts.
The program is only accepted when it compiles with zero errors.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from algoc import CompileError, compile_source  # noqa: E402

ASK_MODEL = os.environ.get("ALGO_ASK_MODEL", "claude-sonnet-5-5")

LANGUAGE_GUIDE = r'''
You write programs in AlgoLang, a small agent-native language. Rules:

1. There are NO functions. The only callable thing is an `agent`. A `flow` orchestrates agents.
2. Exactly one `flow main(...)` is the entry point.
3. Types: text, score (0..1 number), list, json, bool. Only score/number/bool can be compared.
4. Every agent MUST have a `goal`. `{param}` placeholders in the goal must name real parameters.
5. Tools must be declared at top level with `tool a.b` before an agent `uses` them.
6. Models must be declared with `model name = "id"` before an agent uses `model name`.
7. No arithmetic, no loops other than `par for`, no string operators, no comments inside strings.
8. Use policies where sensible: budget tokens N, retry N, timeout S,
   require human when confidence < X, forbid attr1, attr2 (for protected attributes such as
   gender, caste, religion, nationality on agents that make decisions about people).

Syntax:

model smart = "claude-sonnet-5-5"
model fast  = "claude-haiku-5-5"
tool  web.search

agent Planner(task: text) -> list {
    role  "Project planner"
    goal  "Split {task} into 3 to 5 independent sub-tasks"
    model smart
}

agent Worker(subtask: text, task: text) -> text {
    role  "Specialist"
    goal  "Complete {subtask} as part of {task}"
    uses  web.search
    model fast
    policy {
        budget tokens 4000
        retry 1
    }
}

agent Reviewer(work: list) -> score {
    role  "Quality reviewer"
    goal  "Score the combined work {work} from 0 to 1 for quality"
    model smart
    policy { require human when confidence < 0.75 }
}

agent Writer(work: list, tone: text = "clear") -> text {
    goal "Write a final report from {work} in a {tone} tone"
    model fast
}

flow main(task: text) {
    parts   = Planner(task)
    results = par for p in parts { Worker(p, task) }      // parallel, one per item
    [quality, draft] = par { Reviewer(results), Writer(results) }   // parallel block
    if quality < 0.8 {
        draft = Writer(results, tone = "rigorous and detailed")
    }
    emit draft, quality
}

Statements allowed in a flow: assignment from an agent call; `[a, b] = par { A(x), B(x) }`;
`xs = par for v in list_var { A(v) }`; `if x < 0.8 { ... } else { ... }`; `emit a, b`;
a bare agent call. Comments use //.

Reply with ONE complete program in a single ```algo code block and nothing else.
'''


def _extract(text):
    m = re.search(r"```(?:algo|algolang)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"


class AskError(Exception):
    pass


def _client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AskError("Agentic mode needs ANTHROPIC_API_KEY (or use `algo wizard`, which needs no AI).")
    try:
        import anthropic
    except ImportError:
        raise AskError("Agentic mode needs the anthropic package:  pip install anthropic")
    return anthropic.Anthropic()


def write_program(request: str, current: str | None = None, attempts: int = 3,
                  client=None, model: str = ASK_MODEL, log=print):
    """Ask a model to write AlgoLang for `request`; compile; repair until it compiles.

    Returns dict(source, ok, attempts, diagnostics)."""
    client = client or _client()
    user = f"Write an AlgoLang program for this request:\n\n{request}"
    if current:
        user = (f"Here is an existing AlgoLang program:\n\n```algo\n{current}\n```\n\n"
                f"Change it to satisfy this request:\n\n{request}")
    messages = [{"role": "user", "content": user}]
    source, diags = "", []
    for n in range(1, attempts + 1):
        log(f"→ attempt {n}: asking {model} to write the program…")
        msg = client.messages.create(model=model, max_tokens=4000, system=LANGUAGE_GUIDE, messages=messages)
        text = "".join(getattr(b, "text", "") for b in msg.content)
        source = _extract(text)
        try:
            compile_source(source, "ask.algo")
            log(f"✓ attempt {n}: compiles with no errors")
            return dict(source=source, ok=True, attempts=n, diagnostics=[])
        except CompileError as e:
            diags = [str(d) for d in e.diags]
            log(f"✗ attempt {n}: {len(diags)} compile error(s) — sending them back to be fixed")
            for d in diags[:6]:
                log(f"    {d}")
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "The AlgoLang compiler reported these errors:\n"
                          + "\n".join(diags) + "\n\nReturn the corrected complete program."}]
    return dict(source=source, ok=False, attempts=attempts, diagnostics=diags)


# ───────────────────────── pattern templates (offline) ─────────────────────────
PATTERNS = {
    "pipeline": "Pipeline — research, write, then edit, one after another",
    "fanout": "Fan-out / fan-in — plan the parts, work on each in parallel, combine",
    "committee": "Committee — three experts answer in parallel, a judge decides",
    "critic": "Critic & revise — draft, score, redraft if the score is low",
    "router": "Router — classify the input and send it to the right specialist",
    "guardrail": "Guardrail — safety check first, then do the work",
}


def _q(s):
    return s.replace("\\", "/").replace('"', "'").replace("{", "(").replace("}", ")").replace("\n", " ")


def template(pattern: str, purpose: str = "the user's request", inp: str = "request",
             human: float | None = 0.75, forbid: list | None = None, budget: int | None = 4000):
    """Return a complete, compiling AlgoLang program for a pattern."""
    p = _q(purpose)
    pol_lines = []
    if budget:
        pol_lines.append(f"budget tokens {budget}")
    pol = ("    policy {\n" + "".join(f"        {x}\n" for x in pol_lines) + "    }\n") if pol_lines else ""
    dec = []
    if budget:
        dec.append(f"budget tokens {budget}")
    if human is not None:
        dec.append(f"require human when confidence < {human:.2f}")
    if forbid:
        dec.append("forbid " + ", ".join(forbid))
    dpol = ("    policy {\n" + "".join(f"        {x}\n" for x in dec) + "    }\n") if dec else ""
    head = (f"// {pattern} pattern — generated by algo wizard\n// Purpose: {p}\n\n"
            'model smart = "claude-sonnet-5-5"\nmodel fast  = "claude-haiku-5-5"\ntool  web.search\n\n')
    i = inp
    if pattern == "pipeline":
        body = f'''agent Researcher({i}: text) -> text {{
    role  "Research analyst"
    goal  "Gather the key facts needed for: {p}. Input: {{{i}}}"
    uses  web.search
    model smart
{pol}}}

agent Writer(facts: text) -> text {{
    role  "Writer"
    goal  "Write a clear, well-structured answer from these facts: {{facts}}"
    model fast
{pol}}}

agent Editor(draft: text) -> text {{
    role  "Senior editor"
    goal  "Improve accuracy, clarity and tone of this draft: {{draft}}"
    model smart
{pol}}}

flow main({i}: text) {{
    facts = Researcher({i})
    draft = Writer(facts)
    final = Editor(draft)
    emit final
}}
'''
    elif pattern == "fanout":
        body = f'''agent Planner({i}: text) -> list {{
    role  "Planner"
    goal  "Split this into 3 to 5 independent parts for: {p}. Input: {{{i}}}"
    model smart
}}

agent Worker(part: text, {i}: text) -> text {{
    role  "Specialist"
    goal  "Complete this part: {{part}}. Overall task: {{{i}}}"
    uses  web.search
    model fast
{pol}}}

agent Combiner(results: list) -> text {{
    role  "Integrator"
    goal  "Combine these partial results into one coherent answer: {{results}}"
    model smart
{dpol}}}

flow main({i}: text) {{
    parts   = Planner({i})
    results = par for part in parts {{ Worker(part, {i}) }}
    answer  = Combiner(results)
    emit answer
}}
'''
    elif pattern == "committee":
        body = f'''agent ExpertA({i}: text) -> text {{
    role  "Domain expert"
    goal  "Answer from a technical perspective: {{{i}}}"
    model smart
}}

agent ExpertB({i}: text) -> text {{
    role  "Practitioner"
    goal  "Answer from a practical, real-world perspective: {{{i}}}"
    model fast
}}

agent ExpertC({i}: text) -> text {{
    role  "Ethicist"
    goal  "Answer from an ethical and social-impact perspective: {{{i}}}"
    model smart
}}

agent Judge(a: text, b: text, c: text) -> text {{
    role  "Chair of the committee"
    goal  "Weigh these three answers and give one balanced decision for: {p}. Answers: {{a}} | {{b}} | {{c}}"
    model smart
{dpol}}}

flow main({i}: text) {{
    [a, b, c] = par {{ ExpertA({i}), ExpertB({i}), ExpertC({i}) }}
    decision  = Judge(a, b, c)
    emit decision
}}
'''
    elif pattern == "critic":
        body = f'''agent Drafter({i}: text, style: text = "clear") -> text {{
    role  "Author"
    goal  "Produce a {{style}} first version for: {p}. Input: {{{i}}}"
    model fast
{pol}}}

agent Critic(draft: text) -> score {{
    role  "Critical reviewer"
    goal  "Score this draft from 0 to 1 for accuracy and completeness: {{draft}}"
    model smart
{dpol}}}

flow main({i}: text) {{
    draft = Drafter({i})
    if Critic(draft) < 0.8 {{
        draft = Drafter({i}, style = "more rigorous and complete")
    }}
    emit draft
}}
'''
    elif pattern == "router":
        body = f'''agent Classifier({i}: text) -> score {{
    role  "Triage officer"
    goal  "Score from 0 to 1 how technical this request is: {{{i}}}"
    model fast
}}

agent TechnicalExpert({i}: text) -> text {{
    role  "Technical specialist"
    goal  "Give a precise technical answer for: {p}. Request: {{{i}}}"
    model smart
{pol}}}

agent GeneralHelper({i}: text) -> text {{
    role  "Friendly guide"
    goal  "Give a simple, friendly answer for: {p}. Request: {{{i}}}"
    model fast
{pol}}}

flow main({i}: text) {{
    technical = Classifier({i})
    if technical >= 0.5 {{
        answer = TechnicalExpert({i})
    }} else {{
        answer = GeneralHelper({i})
    }}
    emit answer
}}
'''
    elif pattern == "guardrail":
        body = f'''agent SafetyCheck({i}: text) -> bool {{
    role  "Safety reviewer"
    goal  "Answer true only if this request is safe and appropriate to fulfil: {{{i}}}"
    model fast
}}

agent Assistant({i}: text) -> text {{
    role  "Assistant"
    goal  "Help with: {p}. Request: {{{i}}}"
    model smart
{dpol}}}

agent PoliteRefusal({i}: text) -> text {{
    role  "Assistant"
    goal  "Politely explain why this request cannot be fulfilled and suggest a safe alternative: {{{i}}}"
    model fast
}}

flow main({i}: text) {{
    safe = SafetyCheck({i})
    if safe == true {{
        answer = Assistant({i})
    }} else {{
        answer = PoliteRefusal({i})
    }}
    emit answer
}}
'''
    else:
        raise ValueError(f"unknown pattern {pattern}")
    src = head + body
    compile_source(src, "template.algo")   # templates must always compile
    return src


def _ask(prompt, default=""):
    v = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return v or default


def wizard():
    print("AlgoLang wizard — answer a few questions; press Enter to accept the [default].\n")
    purpose = _ask("1. What should your AI system do", "answer student questions about AI")
    print("\n2. Choose a design pattern:")
    keys = list(PATTERNS)
    for n, k in enumerate(keys, 1):
        print(f"   {n}. {PATTERNS[k]}")
    choice = _ask("   Pattern number", "2")
    pattern = keys[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(keys) else "fanout"
    inp = re.sub(r"\W+", "_", _ask("\n3. Name of the input (one word)", "request")).strip("_").lower() or "request"
    h = _ask("4. Send low-confidence decisions to a human? (y/n)", "y").lower().startswith("y")
    human = float(_ask("   Confidence threshold (0-1)", "0.75")) if h else None
    f = _ask("5. Forbid protected attributes in decisions? (y/n)", "y").lower().startswith("y")
    forbid = None
    if f:
        forbid = [x.strip() for x in _ask("   Which ones", "gender, caste, religion, nationality").split(",") if x.strip()]
    budget = int(_ask("6. Token budget per agent", "4000") or 0) or None
    src = template(pattern, purpose, inp, human, forbid, budget)
    default_name = re.sub(r"\W+", "_", purpose.lower()).strip("_")[:30] or "my_program"
    name = _ask("\n7. Save as", default_name + ".algo")
    if not name.endswith(".algo"):
        name += ".algo"
    Path(name).write_text(src, encoding="utf-8")
    print(f"\n✓ wrote {name} ({pattern} pattern) — it compiles with no errors.\n")
    print(src)
    return name, inp


def ask_cli(request, out=None, attempts=3):
    try:
        res = write_program(request, attempts=attempts)
    except AskError as e:
        print(f"✗ {e}")
        return None
    name = out or (re.sub(r"\W+", "_", request.lower()).strip("_")[:40] or "generated") + ".algo"
    if not name.endswith(".algo"):
        name += ".algo"
    Path(name).write_text(res["source"], encoding="utf-8")
    print()
    print(res["source"])
    if res["ok"]:
        print(f"✓ wrote {name} — compiles with no errors after {res['attempts']} attempt(s).")
    else:
        print(f"⚠ wrote {name}, but it still has errors after {res['attempts']} attempts:")
        for d in res["diagnostics"]:
            print(f"  {d}")
    return name if res["ok"] else None
