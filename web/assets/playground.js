// AlgoLang web playground: the real compiler and runtime, running in the browser through Pyodide.
(function () {
  const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
  const $ = s => document.querySelector(s);
  const { highlight, esc } = window.AlgoSite;
  const ta = $("#src"), hl = $("#hl"), status = $("#status"), runBtn = $("#run");
  let py = null, bridge = null, examples = [], catalog = [], lastErrors = [], inputs = [], values = {};

  // ── editor: a transparent textarea over a highlighted <pre> ──
  const gut = $("#gut");
  function paint() {
    const bad = new Set(lastErrors.map(e => e.line));
    const body = highlight(ta.value).split("\n");
    hl.innerHTML = body.map((l, i) => (bad.has(i + 1) ? `<span class="err">${l || " "}</span>` : l)).join("\n") + "\n";
    gut.innerHTML = body.map((_, i) => (bad.has(i + 1) ? `<b>${i + 1}</b>` : i + 1)).join("\n") + "\n";
    sync();
  }
  function sync() { hl.scrollTop = gut.scrollTop = ta.scrollTop; hl.scrollLeft = ta.scrollLeft; }
  ta.addEventListener("scroll", sync);
  ta.addEventListener("keydown", e => {
    if (e.key === "Tab") {
      e.preventDefault();
      const s = ta.selectionStart;
      ta.setRangeText("    ", s, ta.selectionEnd, "end"); changed();
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
  });
  let timer = null;
  function changed() { paint(); clearTimeout(timer); timer = setTimeout(inspect, 350); }
  ta.addEventListener("input", changed);

  // ── input form follows the program's flow main(...) ──
  function renderInputs() {
    const box = $("#inputs");
    box.querySelectorAll("input").forEach(i => (values[i.name] = i.value));
    box.innerHTML = inputs.length ? "" : '<span style="font-size:13.5px;color:#7A869C">This program takes no inputs.</span>';
    for (const name of inputs) {
      const l = document.createElement("label");
      l.innerHTML = `${esc(name)}<input name="${esc(name)}" autocomplete="off">`;
      l.querySelector("input").value = values[name] ?? "";
      l.querySelector("input").addEventListener("keydown", e => { if (e.key === "Enter") run(); });
      box.appendChild(l);
    }
  }

  function showDiagnostics(errs) {
    const pane = $("#p-results");
    pane.innerHTML = `<p class="note">Fix ${errs.length === 1 ? "this error" : "these " + errs.length + " errors"} and the program will run. Error lines are marked in the editor.</p>` +
      errs.map(e => `<div class="diag"><b>${esc(e.code)}</b> line ${e.line}: ${esc(e.msg).replace(/\n/g, "<br>")}</div>`).join("");
    select("results");
  }

  function inspect() {
    if (!bridge) return;
    const r = JSON.parse(bridge.inspect(ta.value));
    lastErrors = r.errors || [];
    paint();
    if (r.ok) {
      inputs = r.inputs; renderInputs();
      status.textContent = `${r.agents.length} agent${r.agents.length === 1 ? "" : "s"} · no errors`;
      runBtn.disabled = false;
    } else {
      // keep the form in step with the code even while it has errors
      const m = ta.value.match(/flow\s+main\s*\(([^)]*)\)/);
      const guess = m ? (m[1].match(/[A-Za-z_]\w*(?=\s*:)/g) || []) : inputs;
      if (guess.join() !== inputs.join()) { inputs = guess; renderInputs(); }
      status.textContent = `${lastErrors.length} error${lastErrors.length === 1 ? "" : "s"}`;
      runBtn.disabled = false;
    }
  }

  function run() {
    if (!bridge) return;
    $("#inputs").querySelectorAll("input").forEach(i => (values[i.name] = i.value));
    const missing = inputs.filter(n => !(values[n] || "").trim());
    if (missing.length) {
      const first = $(`#inputs input[name="${missing[0]}"]`);
      status.textContent = `Fill in ${missing.join(", ")} to run`;
      first && first.focus();
      return;
    }
    status.textContent = "Running…";
    setTimeout(() => {
      const t0 = performance.now();
      const r = JSON.parse(bridge.run(ta.value, JSON.stringify(values)));
      if (r.compile_errors) { lastErrors = r.compile_errors; paint(); showDiagnostics(r.compile_errors); status.textContent = "Not run: fix the errors"; return; }
      renderResult(r);
      status.textContent = `Ran in ${Math.round(performance.now() - t0)} ms`;
    }, 10);
  }

  function fmt(v) {
    if (Array.isArray(v)) return "<ol>" + v.map(x => `<li>${fmt(x)}</li>`).join("") + "</ol>";
    return esc(String(v));
  }

  function renderResult(r) {
    const s = r.stats || {};
    let h = "";
    if (!r.ok) h += `<div class="diag"><b>${esc(r.status.toUpperCase())}</b> ${esc(r.problem || "")}</div>`;
    if (r.escalated) h += `<p class="note">${r.escalated} result${r.escalated === 1 ? " was" : "s were"} below the confidence threshold. In a real deployment ${r.escalated === 1 ? "it waits" : "they wait"} in the human review queue.</p>`;
    if (r.values && r.values.length) {
      h += "<h3>Emitted</h3><ul class='out-values'>" + r.values.map(v => `<li>${fmt(v)}</li>`).join("") + "</ul>";
    }
    h += `<h3>What each agent did</h3><table class="calls"><thead><tr><th>Agent</th><th>Confidence</th><th>Status</th><th>Tokens</th><th>Tools</th></tr></thead><tbody>` +
      (r.calls || []).map(c => `<tr><td>${esc(c.agent)}</td><td>${c.confidence != null ? Number(c.confidence).toFixed(2) : "—"}</td><td class="st-${esc(c.status)}">${esc(c.status)}</td><td>${c.tokens ?? "—"}</td><td>${esc((c.tool_calls || []).map(t => t.tool || t.name || "").join(", "))}</td></tr>`).join("") +
      `</tbody></table><p style="font-size:14px;color:#7A869C;margin-top:12px">${s.calls ?? (r.calls || []).length} calls · ~${s.tokens ?? 0} tokens · offline backend in your browser. Install AlgoLang and add an API key to run with real Claude models.</p>`;
    $("#p-results").innerHTML = h;
    $("#p-python").innerHTML = `<pre>${esc(r.python || "")}</pre>`;
    $("#p-audit").innerHTML = `<p class="note">One record per agent call. Each record carries the hash of the one before it, so editing or deleting a line breaks the chain.</p><pre>${esc((r.audit || []).map(l => { try { return JSON.stringify(JSON.parse(l), null, 2); } catch { return l; } }).join("\n\n"))}</pre>`;
    select("results");
  }

  // ── result tabs ──
  function select(name) {
    document.querySelectorAll(".rtabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab === name));
    document.querySelectorAll(".rpane").forEach(p => (p.hidden = p.id !== "p-" + name));
  }
  document.querySelectorAll(".rtabs button").forEach(b => b.addEventListener("click", () => select(b.dataset.tab)));

  // ── examples and the pack library ──
  async function loadProgram(value) {
    if (value.startsWith("ex:")) {
      const ex = examples[+value.slice(3)];
      ta.value = ex.source; values = Object.assign({}, ex.inputs || {});
    } else if (value.startsWith("pack:")) {
      const p = catalog.find(x => x.id === value.slice(5));
      ta.value = await (await fetch(p.path)).text(); values = {};
    }
    lastErrors = []; changed();
    if (bridge) $("#p-results").innerHTML = '<div class="empty"><h3>Ready</h3><p>Fill in the inputs below the editor and press <b>Run</b> (or Ctrl+Enter).</p></div>';
    $("#p-python").innerHTML = '<p class="empty">Run the program to see the Python the compiler generates.</p>';
    $("#p-audit").innerHTML = '<p class="empty">Run the program to see its audit records.</p>';
    history.replaceState(null, "", "#" + encodeURIComponent(value));
  }
  $("#pick").addEventListener("change", e => loadProgram(e.target.value));
  runBtn.addEventListener("click", run);

  async function boot() {
    const [ex, cat] = await Promise.all([fetch("py/examples.json").then(r => r.json()), fetch("packs/catalog.json").then(r => r.json())]);
    examples = ex; catalog = cat.packs;
    const pick = $("#pick");
    pick.innerHTML = `<optgroup label="Examples">${examples.map((e, i) => `<option value="ex:${i}">${esc(e.title)}</option>`).join("")}</optgroup>` +
      Object.entries(cat.sectors).map(([sid, sname]) => `<optgroup label="${esc(sname)}">${catalog.filter(p => p.sector === sid).map(p => `<option value="pack:${p.id}">${esc(p.title)}</option>`).join("")}</optgroup>`).join("");
    const want = decodeURIComponent(location.hash.slice(1));
    const start = want && [...pick.options].some(o => o.value === want) ? want : "ex:0";
    pick.value = start; await loadProgram(start);

    $("#p-results").innerHTML = '<div class="loader"><div>Starting Python in your browser. The first visit downloads about 10 MB; later visits are instant.<div class="bar2"><i></i></div></div></div>';
    try {
      await new Promise((ok, bad) => { const s = document.createElement("script"); s.src = PYODIDE + "pyodide.js"; s.onload = ok; s.onerror = () => bad(new Error("could not load Pyodide")); document.head.appendChild(s); });
      py = await window.loadPyodide({ indexURL: PYODIDE });
      const zip = await (await fetch("py/algokit.zip")).arrayBuffer();
      py.unpackArchive(zip, "zip", { extractDir: "/home/pyodide/algokit" });
      py.runPython(await (await fetch("py/bridge.py")).text());
      bridge = { inspect: py.globals.get("inspect"), run: py.globals.get("run") };
      const v = py.runPython("version()");
      $("#ver").textContent = "AlgoLang " + v;
      $("#p-results").innerHTML = `<div class="empty"><h3>Ready</h3><p>Edit the program on the left, fill in its inputs and press <b>Run</b> (or Ctrl+Enter). The compiler checks your code as you type.</p><p>Pick any of the 120 domain packs from the menu to see how a real enterprise workflow is built.</p></div>`;
      inspect();
    } catch (err) {
      $("#p-results").innerHTML = `<div class="diag"><b>Could not start Python.</b> ${esc(err.message)}. Check your connection and reload. The playground needs a modern browser with WebAssembly.</div>`;
      status.textContent = "Offline";
    }
  }
  boot();
})();
