// AlgoLang 1.1: launch deck (editable PowerPoint).
// Build:  node docs/presentation/make_deck.js   ->  docs/presentation/AlgoLang_Presentation.pptx
// Needs pptxgenjs, react, react-dom, react-icons, sharp. Palette = the LaTeX deck's colours.
"use strict";
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const RDS = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa6");

const SKILL = process.env.PPTX_SKILL || "";
const OUT = path.join(__dirname, "AlgoLang_Presentation.pptx");

// ── Palette (identical to AlgoLang_Presentation.tex) ──
const HEX = {
  navy: "0B1F3A", navy2: "1D3B66", navylight: "E8EDF5", gold: "C9A227", goldlight: "F3EFE1",
  ink: "1B1B1B", muted: "5A6270", ok: "2F6B3A", bad: "7A1020", term: "0E1A2B", white: "FFFFFF",
};
const THEME = {
  name: "AlgoLang Navy & Gold",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: HEX.ink, lt1: HEX.white, dk2: HEX.navy, lt2: HEX.navylight,
    accent1: HEX.gold, accent2: HEX.navy2, accent3: HEX.goldlight, accent4: HEX.ok,
    accent5: HEX.bad, accent6: HEX.muted, hlink: HEX.navy2, folHlink: HEX.muted,
  },
};
const MONO = "Consolas";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.author = "Dr. S. Satyanarayana, Ph.D., PDF (AI)";
pres.company = "AlgoProfessor AI R&amp;D Solutions";
pres.title = "AlgoLang 1.1: the agent-native programming language";
pres.subject = "AlgoLang language, comparisons and 22 enterprise applications";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const NAVY = C.text2, LIGHT = C.background2, WHITE = C.background1, INK = C.text1;
const GOLD = C.accent1, NAVY2 = C.accent2, GOLDL = C.accent3, OK = C.accent4, BAD = C.accent5, MUTED = C.accent6;
const W = 13.333, H = 7.5;

// ── Icons: react-icons → PNG ──
const iconCache = {};
async function icon(name, color = HEX.gold, size = 256) {
  const key = name + color;
  if (iconCache[key]) return iconCache[key];
  const Comp = fa[name];
  if (!Comp) throw new Error("missing icon " + name);
  const svg = RDS.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return (iconCache[key] = "image/png;base64," + buf.toString("base64"));
}
async function iconDot(slide, name, x, y, d, { fill = NAVY, color = HEX.gold, id = "icon" } = {}) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" }, objectName: id + " circle" });
  const p = d * 0.27;
  slide.addImage({ data: await icon(name, color), x: x + p, y: y + p, w: d - 2 * p, h: d - 2 * p, objectName: id, altText: id });
}

// ── Layouts ──
const footer = (color) => [
  { text: { text: "AlgoLang 1.1  ·  Dr. S. Satyanarayana, Ph.D., PDF (AI)  ·  AlgoProfessor AI R&D Solutions",
    options: { x: 0.6, y: 7.02, w: 9.5, h: 0.3, fontSize: 10, color, fontFace: THEME.bodyFontFace, margin: 0 } } },
];
pres.defineSlideMaster({
  title: "Title", background: { color: NAVY },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.2, w: 11.7, h: 1.4, fontSize: 54, bold: true, color: WHITE, fontFace: THEME.headFontFace, valign: "bottom", align: "left", margin: 0 }, text: "" } },
            { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.7, w: 11.7, h: 1.0, fontSize: 24, color: GOLD, valign: "top", margin: 0 }, text: "" } }],
});
pres.defineSlideMaster({
  title: "Section", background: { color: NAVY },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 2.1, y: 2.75, w: 10.4, h: 1.1, fontSize: 44, bold: true, color: WHITE, fontFace: THEME.headFontFace, valign: "bottom", align: "left", margin: 0 }, text: "" } },
            { placeholder: { options: { name: "body", type: "body", x: 2.1, y: 3.95, w: 10.4, h: 0.9, fontSize: 20, color: LIGHT, valign: "top", margin: 0 }, text: "" } }],
  slideNumber: { x: 12.2, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: GOLD, align: "right" },
});
pres.defineSlideMaster({
  title: "Content", background: { color: WHITE },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.75, fontSize: 30, bold: true, color: NAVY, fontFace: THEME.headFontFace, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 1.1, w: 12.1, h: 0.45, fontSize: 16, color: GOLD, italic: true, valign: "top", margin: 0 }, text: "" } },
    { line: { x: 0.6, y: 6.92, w: 12.13, h: 0, line: { color: LIGHT, width: 1 } } },
    ...footer(MUTED),
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.53, h: 0.3, fontSize: 10, color: MUTED, align: "right" },
});

let section = "";
function add(master, title, sub) {
  const s = pres.addSlide({ masterName: master, sectionTitle: section });
  if (title) s.addText(title, { placeholder: "title" });
  if (sub) s.addText(sub, { placeholder: "body" });
  return s;
}
function sec(t) { section = t; pres.addSection({ title: t }); }
async function divider(num, title, sub, ic) {
  const s = add("Section", title, sub);
  await iconDot(s, ic, 0.8, 2.85, 1.0, { fill: GOLD, color: HEX.navy, id: "section icon" });
  s.addText(num, { x: 2.1, y: 2.2, w: 3, h: 0.5, fontSize: 16, bold: true, color: GOLD, charSpacing: 1, margin: 0, isTextBox: true });
  return s;
}
const T = (s, text, o) => s.addText(text, { isTextBox: true, margin: 0, color: INK, fontSize: 16, valign: "top", ...o });
function card(s, x, y, w, h, { fill = LIGHT, line, id = "card" } = {}) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: line ? { color: line, width: 1.25 } : { type: "none" }, objectName: id });
}
function bullets(items, o = {}) {
  return items.map((t, i) => {
    const runs = Array.isArray(t) ? t : [{ text: t }];
    return runs.map((r, j) => ({ text: r.text, options: { ...(r.options || {}), ...(j === 0 ? { bullet: { code: "25A0", indent: 18 }, paraSpaceAfter: o.gap ?? 6 } : {}), ...(j === runs.length - 1 && i < items.length - 1 ? { breakLine: true } : {}) } }));
  }).flat();
}
const B = (text) => ({ text, options: { bold: true, color: NAVY } });

// ── Code with simple AlgoLang highlighting ──
const KW = new Set(["risk", "disclose", "agent", "flow", "goal", "uses", "policy", "budget", "tokens", "redact", "pii", "samples", "require", "approvals", "forbid", "explain", "with", "evidence", "if", "else", "emit", "type", "eval", "on", "case", "expect", "human", "when", "confidence", "par", "for", "model", "use", "and", "def", "return", "raise", "in"]);
const TY = new Set(["text", "score", "uncertain", "number", "bool", "list", "json"]);
function codeRuns(src) {
  const runs = [];
  const lines = src.split("\n");
  lines.forEach((ln, li) => {
    const re = /(\/\/.*$|#.*$|"[^"]*"|[A-Za-z_][A-Za-z0-9_.]*|\s+|.)/g;
    let m; const parts = [];
    while ((m = re.exec(ln))) {
      const t = m[0]; let color = "D6DEEA";
      if (t.startsWith("//") || t.startsWith("#")) color = "8C98AB";
      else if (t.startsWith('"')) color = "9CCB8E";
      else if (KW.has(t)) color = HEX.gold;
      else if (TY.has(t)) color = "7FB2F0";
      else if (/^[A-Z]/.test(t)) color = "FFFFFF";
      parts.push({ text: t, options: { color } });
    }
    if (!parts.length) parts.push({ text: " ", options: { color: "D6DEEA" } });
    if (li < lines.length - 1) parts[parts.length - 1].options.breakLine = true;
    runs.push(...parts);
  });
  return runs;
}
function codeBox(s, src, x, y, w, h, fs = 13, id = "code") {
  card(s, x, y, w, h, { fill: HEX.term, id: id + " panel" });
  s.addText(codeRuns(src), { x: x + 0.25, y: y + 0.2, w: w - 0.5, h: h - 0.4, fontFace: MONO, fontSize: fs, valign: "top", margin: 0, isTextBox: true, objectName: id, lineSpacingMultiple: 1.05 });
}

// ── Tables ──
function table(s, head, rows, { x = 0.6, y = 1.75, w = 12.13, colW, fs = 13, firstBold = true, highlight = 0, rowH = 0.42 } = {}) {
  const hdr = head.map((t) => ({ text: t, options: { bold: true, color: WHITE, fill: { color: HEX.navy }, fontSize: fs } }));
  const body = rows.map((r, i) => r.map((t, j) => {
    const o = { fontSize: fs, color: HEX.ink, fill: { color: i === highlight - 1 ? HEX.goldlight : i % 2 ? "F6F8FB" : HEX.white } };
    if (j === 0 && firstBold) { o.bold = true; o.color = HEX.navy; }
    return typeof t === "object" ? { text: t.text, options: { ...o, ...t.options } } : { text: t, options: o };
  }));
  s.addTable([hdr, ...body], { x, y, w, colW, rowH, fontFace: THEME.bodyFontFace, border: { type: "solid", pt: 0.75, color: "D5DCE6" }, valign: "middle", margin: [3, 6, 3, 6] });
}

// ── Applications (all 22 in enterprise-apps/): shared with the LaTeX deck via apps.json ──
const APPS = require("./apps.json").map((a) => [a.group, a.dir, a.name, a.sector, a.icon, a.risk, a.programs, a.challenge, a.does, a.governance, a.tools]);
if (APPS.length !== 22) throw new Error("expected 22 apps, got " + APPS.length);

const RISK = { minimal: [OK, "MINIMAL RISK"], limited: [GOLD, "LIMITED RISK"], high: [BAD, "HIGH RISK"] };

async function appCard(s, a, x, y, w, h, idx) {
  const [, dir, name, sector, ic, risk, progs, challenge, does, gov, tools] = a;
  const id = "app " + (idx + 1);
  card(s, x, y, w, h, { fill: WHITE, line: "D5DCE6", id: id + " card" });
  await iconDot(s, ic, x + 0.3, y + 0.3, 0.8, { id: id + " icon" });
  T(s, name, { x: x + 1.3, y: y + 0.28, w: w - 1.55, h: 0.45, fontSize: name.length > 30 ? 16.5 : 19, bold: true, color: NAVY, fontFace: THEME.headFontFace, fit: "shrink" });
  T(s, sector, { x: x + 1.3, y: y + 0.74, w: w - 3.3, h: 0.35, fontSize: 13, color: GOLD, bold: true });
  const [rc, rl] = RISK[risk];
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + w - 1.95, y: y + 0.76, w: 1.7, h: 0.3, rectRadius: 0.15, fill: { color: rc }, line: { type: "none" }, objectName: id + " risk" });
  T(s, rl, { x: x + w - 1.95, y: y + 0.76, w: 1.7, h: 0.3, fontSize: 10, bold: true, color: WHITE, align: "center", valign: "middle", charSpacing: 1 });
  T(s, [{ text: "Challenge  ", options: { bold: true, color: NAVY } }, { text: challenge }], { x: x + 0.3, y: y + 1.3, w: w - 0.6, h: 0.75, fontSize: 14, color: INK });
  T(s, "WHAT IT DOES", { x: x + 0.3, y: y + 2.12, w: 3, h: 0.3, fontSize: 11, bold: true, color: MUTED, charSpacing: 2 });
  T(s, bullets(does, { gap: 4 }), { x: x + 0.3, y: y + 2.42, w: w - 0.6, h: 1.45, fontSize: 14, color: INK });
  card(s, x + 0.3, y + 3.95, w - 0.6, 0.55, { fill: GOLDL, id: id + " governance" });
  s.addImage({ data: await icon("FaShieldHalved", HEX.navy), x: x + 0.45, y: y + 4.07, w: 0.3, h: 0.3, altText: "governance" });
  T(s, gov, { x: x + 0.85, y: y + 3.95, w: w - 1.3, h: 0.55, fontSize: 13, bold: true, color: NAVY, valign: "middle" });
  T(s, [{ text: tools.join("  "), options: { fontFace: MONO, color: NAVY2 } }], { x: x + 0.3, y: y + 4.65, w: w - 1.6, h: 0.3, fontSize: 11, valign: "middle" });
  T(s, `${progs} program${progs > 1 ? "s" : ""}`, { x: x + w - 1.3, y: y + 4.65, w: 1.05, h: 0.3, fontSize: 11, color: MUTED, align: "right", valign: "middle" });
}

(async () => {
  // ═══ 1 · Title ═══
  sec("Opening");
  {
    const s = add("Title", "AlgoLang 1.1", "The agent-native programming language for trustworthy AI");
    await iconDot(s, "FaCodeBranch", 0.8, 0.8, 1.0, { fill: GOLD, color: HEX.navy, id: "logo" });
    T(s, "Agents, not functions.  Checked, explained, signed and tested before they ship.", { x: 0.8, y: 4.55, w: 11.7, h: 0.5, fontSize: 18, color: WHITE, italic: true });
    T(s, [{ text: "Dr. S. Satyanarayana, Ph.D., PDF (AI)", options: { bold: true, color: WHITE, breakLine: true } },
          { text: "Founder, CEO & Chief Agentic AI Scientist  ·  AlgoProfessor AI R&D Solutions, Hyderabad", options: { color: LIGHT } }],
      { x: 0.8, y: 5.75, w: 9, h: 0.8, fontSize: 16 });
    T(s, "github.com/drssnaiml1-cell/algolang", { x: 8.3, y: 6.65, w: 4.2, h: 0.35, fontSize: 13, color: GOLD, align: "right", fontFace: MONO });
    s.addNotes("AlgoLang 1.1: a programming language whose unit of computation is a governed AI agent. Presented by Dr. S. Satyanarayana.");
  }

  // ═══ 2 · Agenda ═══
  {
    const s = add("Content", "Agenda", "From the problem to 22 working applications");
    const items = [["01", "Why a new language", "Four questions every AI decision should answer", "FaCircleQuestion"],
      ["02", "The language", "Agents, flows, policies, uncertainty, typed messages", "FaCode"],
      ["03", "Compared with the field", "General-purpose, scientific and AI languages; agent frameworks", "FaTableColumns"],
      ["04", "22 enterprise applications", "From insurance and banking to quantum AI and smart cities", "FaLayerGroup"],
      ["05", "Platform & roadmap", "AlgoIR, AlgoVM, packages, Studio, MCP; all releases shipped", "FaRoad"],
      ["06", "Build with us", "Applications, pilots and research partnerships", "FaHandshake"]];
    for (let i = 0; i < items.length; i++) {
      const [n, t, d, ic] = items[i]; const col = i % 2, row = Math.floor(i / 2);
      const x = 0.6 + col * 6.2, y = 1.85 + row * 1.6;
      card(s, x, y, 5.95, 1.35, { id: "agenda " + n });
      await iconDot(s, ic, x + 0.25, y + 0.3, 0.75, { id: "agenda icon " + n });
      T(s, n, { x: x + 1.2, y: y + 0.2, w: 1, h: 0.35, fontSize: 13, bold: true, color: GOLD });
      T(s, t, { x: x + 1.2, y: y + 0.48, w: 4.5, h: 0.4, fontSize: 20, bold: true, color: NAVY, fontFace: THEME.headFontFace });
      T(s, d, { x: x + 1.2, y: y + 0.88, w: 4.6, h: 0.35, fontSize: 14, color: MUTED });
    }
  }

  // ═══ Section 1 ═══
  sec("Why AlgoLang");
  await divider("01", "Why a new language", "AI agents now make decisions about people and money. Our languages were not built for that.", "FaCircleQuestion");
  {
    const s = add("Content", "The problem", "Agent frameworks make AI easy to build, but hard to trust");
    T(s, bullets([
      [B("Governance is optional. "), { text: "Budgets, reviews and audit are library calls a developer must remember." }],
      [B("Uncertainty is hidden. "), { text: "A model's answer looks equally sure whether it is right or guessing." }],
      [B("Fairness is untested. "), { text: "Bias is found after release, by the people it harms." }],
      [B("Evidence is missing. "), { text: "Logs can be edited; regulators ask who decided, and why." }],
    ], { gap: 14 }), { x: 0.6, y: 1.9, w: 6.6, h: 4.6, fontSize: 18 });
    card(s, 7.6, 1.9, 5.13, 4.7, { fill: NAVY, id: "four questions" });
    T(s, "Four questions every AI decision should answer", { x: 7.95, y: 2.15, w: 4.5, h: 0.9, fontSize: 20, bold: true, color: GOLD, fontFace: THEME.headFontFace });
    const q = ["Who was allowed to decide?", "Why was this the decision?", "Was it fair and robust?", "Can an auditor prove what happened?"];
    q.forEach((t, i) => {
      T(s, String(i + 1), { x: 7.95, y: 3.25 + i * 0.78, w: 0.5, h: 0.55, fontSize: 30, bold: true, color: GOLD, fontFace: THEME.headFontFace, valign: "middle" });
      T(s, t, { x: 8.55, y: 3.25 + i * 0.78, w: 3.9, h: 0.55, fontSize: 17, color: WHITE, valign: "middle" });
    });
  }
  {
    const s = add("Content", "What AlgoLang is", "A programming language with no functions: only agents and flows");
    const cols = [["FaRobot", "Agent", "Role, goal, tools, model and policy. Returns text, score, list, a typed message or uncertain<T>."],
      ["FaDiagramProject", "Flow", "The only other construct: call agents, run them in parallel, branch on verdicts, emit results."],
      ["FaShieldHalved", "Guarantees", "Policies, budgets, human review and a signed audit log, enforced by the compiler and runtime."]];
    for (let i = 0; i < 3; i++) {
      const x = 0.6 + i * 4.1;
      card(s, x, 1.9, 3.85, 3.6, { id: "construct " + cols[i][1] });
      await iconDot(s, cols[i][0], x + 1.45, 2.2, 0.95, { id: cols[i][1] + " icon" });
      T(s, cols[i][1], { x: x + 0.3, y: 3.3, w: 3.25, h: 0.5, fontSize: 24, bold: true, color: NAVY, align: "center", fontFace: THEME.headFontFace });
      T(s, cols[i][2], { x: x + 0.3, y: 3.85, w: 3.25, h: 1.5, fontSize: 16, color: INK, align: "center" });
    }
    T(s, "Designed by Dr. S. Satyanarayana at AlgoProfessor AI R&D Solutions, Hyderabad.  Open source, Apache 2.0.", { x: 0.6, y: 5.95, w: 12.1, h: 0.4, fontSize: 15, color: MUTED, italic: true, align: "center" });
  }

  // ═══ Section 2 ═══
  sec("The language");
  await divider("02", "The language", "Policies are code. Uncertainty is a type. Evidence is the default.", "FaCode");
  {
    const s = add("Content", "Design principles", "Eight ideas that shape every program");
    const P = [["FaRobot", "Agents, not functions", "The unit of computation is an accountable agent."],
      ["FaScroll", "Policies are code", "Budgets, forbidden attributes and reviewers checked before running."],
      ["FaChartSimple", "Uncertainty is a type", "uncertain<score> samples several times and carries confidence."],
      ["FaCodeBranch", "Deterministic guards", "Branch on tool verdicts, not model moods."],
      ["FaUserCheck", "People stay in charge", "require human, four-eyes approvals, escalation queues."],
      ["FaFileSignature", "Evidence by default", "A hash-chained, signed audit record for every call."],
      ["FaVialCircleCheck", "Tested like software", "Quality, fairness and robustness evals in CI."],
      ["FaPlug", "Offline first", "A deterministic mock model: every program runs without a key."]];
    for (let i = 0; i < 8; i++) {
      const col = i % 4, row = Math.floor(i / 4), x = 0.6 + col * 3.07, y = 1.85 + row * 2.5;
      card(s, x, y, 2.85, 2.3, { id: "principle " + (i + 1) });
      await iconDot(s, P[i][0], x + 0.25, y + 0.25, 0.65, { id: P[i][1] + " icon" });
      T(s, P[i][1], { x: x + 0.25, y: y + 1.0, w: 2.4, h: 0.4, fontSize: 16, bold: true, color: NAVY });
      T(s, P[i][2], { x: x + 0.25, y: y + 1.4, w: 2.4, h: 0.85, fontSize: 13.5, color: INK });
    }
  }
  {
    const s = add("Content", "The language at a glance", "A governed loan decision in 18 lines");
    codeBox(s, `risk high "Retail credit decisions"
disclose "An AI system assisted this decision."

agent Affordability(app: text) -> score {
    goal   "Debt-to-income ratio for {app}"
    uses   bureau.pull
    policy { budget tokens 2000  redact pii }
}
agent Committee(app: text, dti: score) -> uncertain<score> {
    goal   "Recommend approval for {app}"
    policy { samples 5  require approvals 2
             forbid gender, religion  explain with evidence }
}
flow main(app: text) {
    dti = Affordability(app)
    if dti > 0.5 { emit Decline(app, dti) }
    else         { emit Committee(app, dti) }
}`, 0.6, 1.8, 7.6, 4.9, 13.5, "loan program");
    const notes = [["risk high", "The compiler demands oversight, fairness tests, PII redaction and signed audit."],
      ["budget · forbid", "Refused at compile time if violated."],
      ["uncertain<score>", "Five samples, a mean and a confidence."],
      ["require approvals 2", "Four-eyes review before release."],
      ["every call", "A signed, hash-chained audit record."]];
    notes.forEach(([k, v], i) => {
      const y = 1.8 + i * 0.99;
      card(s, 8.5, y, 4.23, 0.85, { id: "note " + (i + 1) });
      T(s, k, { x: 8.7, y: y + 0.08, w: 3.9, h: 0.3, fontSize: 13, bold: true, color: NAVY, fontFace: MONO });
      T(s, v, { x: 8.7, y: y + 0.38, w: 3.9, h: 0.45, fontSize: 13, color: INK });
    });
  }
  {
    const s = add("Content", "Compiler and runtime", "From source to governed execution");
    const box = (x, y, w, t, sub, gold, id) => {
      card(s, x, y, w, 1.0, { fill: gold ? GOLDL : LIGHT, line: gold ? "C9A227" : "1D3B66", id });
      T(s, [{ text: t, options: { bold: true, color: NAVY, breakLine: true } }, { text: sub, options: { color: MUTED, fontSize: 12 } }], { x, y: y + 0.15, w, h: 0.75, fontSize: 15, align: "center" });
    };
    const arrow = (x1, y1, x2, y2) => s.addShape(pres.shapes.LINE, { x: x1, y: Math.min(y1, y2), w: x2 - x1, h: Math.abs(y2 - y1), flipV: y2 < y1, line: { color: NAVY, width: 1.75, endArrowType: "triangle" } });
    box(0.6, 2.4, 1.6, ".algo", "source", false, "source");
    box(2.6, 2.4, 1.75, "Parser", "grammar → AST", false, "parser");
    box(4.75, 2.4, 1.85, "Checker", "E100–E134", true, "checker");
    box(7.05, 1.75, 1.75, "Python", "compiled code", false, "python");
    box(7.05, 3.05, 1.75, "AlgoIR", "signed JSON → AlgoVM", false, "algoir");
    box(9.25, 2.4, 1.85, "Runtime", "policies · budgets · review", true, "runtime");
    box(11.45, 2.4, 1.28, "Audit", "signed log", false, "audit");
    arrow(2.2, 2.9, 2.6, 2.9); arrow(4.35, 2.9, 4.75, 2.9); arrow(6.6, 2.9, 7.05, 2.25); arrow(6.6, 2.9, 7.05, 3.55);
    arrow(8.8, 2.25, 9.25, 2.9); arrow(8.8, 3.55, 9.25, 2.9); arrow(11.1, 2.9, 11.45, 2.9);
    const facts = [["35", "compile-time checks", "Undeclared tools, budgets, forbidden attributes, type errors, unsafe high-risk programs."],
      ["223", "programs, two engines", "Compiled Python and the AlgoVM give identical results in CI."],
      ["4", "model backends", "Claude, OpenAI-compatible local models, offline mock, replay from traces."]];
    facts.forEach(([n, l, d], i) => {
      const x = 0.6 + i * 4.1;
      card(s, x, 4.5, 3.85, 2.1, { id: "fact " + l });
      T(s, [{ text: n + "  ", options: { fontSize: 36, bold: true, color: GOLD, fontFace: THEME.headFontFace } }, { text: l, options: { fontSize: 16, bold: true, color: NAVY } }], { x: x + 0.3, y: 4.62, w: 3.3, h: 0.75, valign: "bottom" });
      T(s, d, { x: x + 0.3, y: 5.5, w: 3.3, h: 1.0, fontSize: 13.5, color: INK });
    });
  }
  {
    const s = add("Content", "Governance built into the language", "Declared once, enforced everywhere");
    table(s, ["Control", "What it does", "Syntax"], [
      ["Token, cost, energy budgets", "Checked before every call; INR and USD; Wh and CO₂", { text: "budget cost 0.04 usd", options: { fontFace: MONO, color: HEX.navy2 } }],
      ["Forbidden attributes", "A protected attribute in a goal or prompt does not compile", { text: "forbid gender, caste", options: { fontFace: MONO, color: HEX.navy2 } }],
      ["Human review", "By rule, by confidence or always; a persistent review queue", { text: "require human when confidence < 0.8", options: { fontFace: MONO, color: HEX.navy2 } }],
      ["Four-eyes approval", "Two different people must approve", { text: "require approvals 2", options: { fontFace: MONO, color: HEX.navy2 } }],
      ["Tool permissions", "Only declared tools; untrusted tools are fenced", { text: "tool web.fetch untrusted", options: { fontFace: MONO, color: HEX.navy2 } }],
      ["Organisation policy", "Org-wide caps that no program can loosen", { text: "algo.config.json", options: { fontFace: MONO, color: HEX.navy2 } }],
      ["Risk levels", "Minimal · limited · high, each with required safeguards", { text: 'risk high "purpose"', options: { fontFace: MONO, color: HEX.navy2 } }],
      ["QPU budgets", "Quantum seconds and dollars capped like tokens", { text: "budget qpu 30 seconds", options: { fontFace: MONO, color: HEX.navy2 } }],
    ], { colW: [2.8, 4.73, 4.6], fs: 14, rowH: 0.52 });
  }
  {
    const s = add("Content", "Trustworthy AI as evidence, not a claim", "What an auditor receives from every AlgoLang program");
    const L = [["FaTriangleExclamation", "Risk levels", "Change what the compiler demands."], ["FaUserSecret", "Privacy", "redact pii; protected values withheld even with typos."],
      ["FaComments", "Explanations", "explain with evidence quotes inputs and tool results."], ["FaLock", "Untrusted tools", "Fenced against prompt injection; MCP servers pinned by SHA-256."],
      ["FaSignature", "Signed audit", "Ed25519, ML-DSA (FIPS 204) or hybrid post-quantum signatures."], ["FaBoxArchive", "Retention", "Audit and trace retention with signed checkpoints."],
      ["FaIdCard", "System cards", "System cards and trust reports generated from the program."], ["FaFileZipper", "Evidence packs", "A signed zip for auditors, verifiable offline."]];
    for (let i = 0; i < 8; i++) {
      const col = i % 2, row = Math.floor(i / 2), x = 0.6 + col * 6.2, y = 1.85 + row * 1.23;
      await iconDot(s, L[i][0], x, y + 0.08, 0.72, { id: L[i][1] + " icon" });
      T(s, L[i][1], { x: x + 0.95, y: y + 0.02, w: 4.9, h: 0.4, fontSize: 18, bold: true, color: NAVY });
      T(s, L[i][2], { x: x + 0.95, y: y + 0.45, w: 4.9, h: 0.5, fontSize: 15, color: INK });
    }
  }
  {
    const s = add("Content", "Uncertainty and evals", "Quality, fairness and robustness tested like code");
    codeBox(s, `eval trust on main {
    case "salaried" (app = "APP-3101 ...") {
        expect status ok
        expect fair across gender [woman, man]
        expect robust (typos, paraphrase, reorder)
               consistency >= 0.9
        expect explained
    }
}`, 0.6, 1.8, 6.4, 3.4, 14, "eval program");
    card(s, 7.3, 1.8, 5.43, 3.4, { fill: HEX.term, id: "eval output panel" });
    T(s, [
      { text: "$ ", options: { color: HEX.gold } }, { text: "algo eval programs/loan_decision.algo", options: { color: "D6DEEA", breakLine: true } },
      { text: "✓ ", options: { color: "7BC67E" } }, { text: "salaried applicant", options: { color: "FFFFFF", breakLine: true } },
      { text: "  fair across gender: same decision, gap 0.000", options: { color: "D6DEEA", breakLine: true } },
      { text: "  robust to typos, paraphrase, reorder:", options: { color: "D6DEEA", breakLine: true } },
      { text: "  consistency 1.00 over 6 variants", options: { color: "D6DEEA", breakLine: true } },
      { text: "✓ ", options: { color: "7BC67E" } }, { text: "self-employed applicant", options: { color: "FFFFFF", breakLine: true } },
      { text: "  2/2 cases pass", options: { color: HEX.gold } },
    ], { x: 7.55, y: 2.0, w: 5.0, h: 3.0, fontFace: MONO, fontSize: 13, isTextBox: true, margin: 0, valign: "top" });
    card(s, 0.6, 5.45, 12.13, 1.2, { fill: GOLDL, id: "uncertainty note" });
    T(s, [B("uncertain<T>  "), { text: "samples an agent several times; flows branch on .confidence; low confidence goes to a person. Evals run in CI on Linux, macOS and Windows." }],
      { x: 0.9, y: 5.45, w: 11.6, h: 1.2, fontSize: 16, valign: "middle" });
  }
  {
    const s = add("Content", "Typed agent-to-agent messages", "New in 1.0: agents exchange checked records, not loose text");
    codeBox(s, `type Party { name: text, phone_verified: bool }
type Claim { policy: text, amount: number,
             fraud_risk: score, claimant: Party }

agent Intake(note: text) -> Claim {
    goal "Fill in every field of the claim in {note}"
}
flow main(note: text) {
    claim = Intake(note)
    if claim.amount < 50000 and claim.fraud_risk < 0.7 {
        emit FastTrack(claim)
    } else {
        emit Investigate(claim, claim.amount)
    }
}`, 0.6, 1.8, 7.6, 4.85, 14, "typed messages program");
    const pts = ["Fields and argument types checked by the compiler (E131, E132)", "Every model answer validated against the type at run time", "The live model is told the exact JSON shape", "PII masked field by field"];
    for (let i = 0; i < pts.length; i++) {
      const y = 1.8 + i * 1.22;
      await iconDot(s, "FaCheck", 8.55, y + 0.1, 0.6, { id: "typed point " + (i + 1) });
      T(s, pts[i], { x: 9.35, y, w: 3.38, h: 0.95, fontSize: 16, valign: "middle" });
    }
  }
  {
    const s = add("Content", "New in 1.1: accountable decisions", "Three questions every governed AI decision raises, answered by the program itself");
    const F = [["FaFileShield", "Is every answer within its limits?", "Agent contracts", "ensure", "Checked on every answer. Broken → one more try → a person. Each audit record says which contracts held."],
      ["FaCodeCompare", "Would the decision have been different?", "What-if audits", "algo whatif", "Re-runs a recorded decision with one input changed; unaffected agents are replayed, so the comparison is exact."],
      ["FaShieldHalved", "Did this change weaken a safeguard?", "Governance diff", "algo diff", "Marks every policy, tool, contract and eval change as loosened, tightened or changed. Fails CI when loosened."]];
    for (let i = 0; i < 3; i++) {
      const x = 0.6 + i * 4.1;
      card(s, x, 1.75, 3.85, 2.75, { fill: i === 1 ? NAVY : LIGHT, id: F[i][2] + " card" });
      await iconDot(s, F[i][0], x + 0.25, 1.95, 0.62, { fill: i === 1 ? GOLD : NAVY, color: i === 1 ? HEX.navy : HEX.gold, id: F[i][2] + " icon" });
      T(s, F[i][1], { x: x + 1.0, y: 1.95, w: 2.7, h: 0.62, fontSize: 13.5, italic: true, color: i === 1 ? GOLD : GOLD, valign: "middle" });
      T(s, [{ text: F[i][2] + "  ", options: { bold: true, color: i === 1 ? WHITE : NAVY, fontFace: THEME.headFontFace, fontSize: 19 } },
            { text: F[i][3], options: { fontFace: MONO, color: i === 1 ? GOLD : NAVY2, fontSize: 13 } }], { x: x + 0.25, y: 2.72, w: 3.4, h: 0.45, valign: "middle" });
      T(s, F[i][4], { x: x + 0.25, y: 3.2, w: 3.4, h: 1.2, fontSize: 13.5, color: i === 1 ? WHITE : INK });
    }
    codeBox(s, `agent Payout(claim: Claim, cover: number) -> number {
    goal   "Fair payout for {claim}"
    ensure result >= 0     else "never negative"
    ensure result <= cover else "never above cover"
}`, 0.6, 4.7, 5.9, 2.0, 12, "contracts code");
    card(s, 6.75, 4.7, 5.98, 2.0, { fill: HEX.term, id: "whatif and diff output" });
    T(s, [
      { text: "$ ", options: { color: HEX.gold } }, { text: "algo whatif run.trace.json --set cover=5000", options: { color: "D6DEEA", breakLine: true } },
      { text: "  2 of 3 calls re-computed · ", options: { color: "D6DEEA" } }, { text: "✗ the decision changed", options: { color: "E58C8C", breakLine: true } },
      { text: "$ ", options: { color: HEX.gold } }, { text: "algo diff git:main:claims.algo claims.algo", options: { color: "D6DEEA", breakLine: true } },
      { text: "  ▼ loosened ", options: { color: "E58C8C" } }, { text: "Payout  contract removed", options: { color: "D6DEEA", breakLine: true } },
      { text: "  ▼ loosened ", options: { color: "E58C8C" } }, { text: "Payout  'gender' allowed again", options: { color: "D6DEEA" } },
    ], { x: 6.95, y: 4.85, w: 5.6, h: 1.75, fontFace: MONO, fontSize: 12, isTextBox: true, margin: 0, valign: "top" });
  }
  {
    const s = add("Content", "Beyond the core", "Streams, quantum, interoperability and an ecosystem");
    const X = [["FaWaveSquare", "AlgoPulse™", "Event streams in the language: topics, keys, dedupe, escalation and dead-letter topics, back-pressure."],
      ["FaAtom", "Quantum AI", "Simulator, noisy simulators, IBM, Braket and Azure backends (ready for hardware); QPU budgets; VERIFIED / BOUNDED answers."],
      ["FaPlug", "Interoperability", "Flows and agents as MCP servers; typed inputs; token streaming; cost and energy dashboard."],
      ["FaCubes", "Ecosystem", "AlgoIR and AlgoVM, signed packages and a registry, Studio with SSO and roles, VS Code, Python SDK."]];
    for (let i = 0; i < 4; i++) {
      const x = 0.6 + i * 3.07;
      card(s, x, 1.85, 2.85, 4.75, { fill: i % 2 ? NAVY : LIGHT, id: X[i][1] + " card" });
      await iconDot(s, X[i][0], x + 0.3, 2.15, 0.85, { fill: i % 2 ? GOLD : NAVY, color: i % 2 ? HEX.navy : HEX.gold, id: X[i][1] + " icon" });
      T(s, X[i][1], { x: x + 0.3, y: 3.2, w: 2.3, h: 0.5, fontSize: 20, bold: true, color: i % 2 ? GOLD : NAVY, fontFace: THEME.headFontFace });
      T(s, X[i][2], { x: x + 0.3, y: 3.8, w: 2.3, h: 2.6, fontSize: 15, color: i % 2 ? WHITE : INK });
    }
  }

  // ═══ Section 3 ═══
  sec("Comparisons");
  await divider("03", "Compared with the field", "Every language is designed for something. AlgoLang is designed for governed AI decisions.", "FaTableColumns");
  {
    const s = add("Content", "General-purpose languages", "What each language is designed for");
    table(s, ["Language", "Paradigm", "Typing", "Concurrency", "Strength"], [
      ["AlgoLang", "Agent-oriented, declarative flows", "Static: text, score, list, json, number, typed messages", "par, par for, streams", "Governed AI decisions: policies, review, audit, evals"],
      ["Python", "Multi-paradigm", "Dynamic (optional hints)", "Threads, asyncio, processes", "Ecosystem for AI, data and scripting"],
      ["Java", "Object-oriented", "Static", "Threads, virtual threads", "Large enterprise systems on the JVM"],
      ["C / C++", "Procedural / multi-paradigm", "Static", "Threads", "Performance, systems, embedded"],
      ["JavaScript / TS", "Multi-paradigm", "Dynamic / static (TS)", "Event loop, async/await", "Web and full-stack applications"],
      ["Rust", "Multi-paradigm, ownership", "Static", "Threads, async; data-race freedom", "Memory safety without a garbage collector"],
      ["Go", "Procedural, CSP", "Static", "Goroutines and channels", "Cloud services and tooling"],
    ], { colW: [1.9, 2.5, 2.9, 2.3, 2.53], fs: 13.5, highlight: 1, rowH: 0.62 });
  }
  {
    const s = add("Content", "Scientific and AI languages", "Where AlgoLang sits beside them");
    table(s, ["Language", "Focus", "Core idea", "Relation to AlgoLang"], [
      ["AlgoLang", "Governed AI agents", "Agents with policies; uncertainty and evals as language features", "—"],
      ["R", "Statistics", "Vectorised data analysis, rich statistical libraries", "Analysis tools inside agents"],
      ["Julia", "Scientific computing", "Multiple dispatch, JIT compilation", "Numerical tools inside agents"],
      ["MATLAB", "Engineering maths", "Matrices, toolboxes", "Engineering tools inside agents"],
      ["SQL", "Data querying", "Declarative relational queries", "Data access tools for agents"],
      ["Prolog", "Logic programming", "Facts, rules, unification", "Symbolic rules beside model agents"],
      ["Lisp", "Symbolic AI", "Code as data, macros", "Historic AI language; no governance layer"],
      ["LMQL", "Constrained LLM prompting", "Queries with constraints on model output", "Prompt-level; AlgoLang is program-level"],
      ["Q# / Qiskit", "Quantum programming", "Quantum circuits and algorithms", "AlgoLang calls circuits as verified tools"],
    ], { colW: [1.9, 2.6, 4.0, 3.63], fs: 13.5, highlight: 1, rowH: 0.5 });
  }
  {
    const s = add("Content", "Agent frameworks", "Libraries add agents to a language; AlgoLang makes them the language");
    table(s, ["Framework", "Form", "Approach", "Governance"], [
      ["AlgoLang", "Language + compiler", "Agents and flows as syntax; checked before running", { text: "Built in: compile time and run time", options: { bold: true, color: HEX.ok } }],
      ["LangChain / LangGraph", "Python, JS library", "Chains and stateful agent graphs", "Added by the developer in code"],
      ["CrewAI", "Python library", "Role-based crews of agents", "Added by the developer in code"],
      ["AutoGen", "Python, .NET library", "Multi-agent conversations", "Added by the developer in code"],
      ["Semantic Kernel", "C#, Python, Java SDK", "Plugins and planners in enterprise apps", "Added by the developer in code"],
      ["DSPy", "Python library", "Declarative LM programs, optimised prompts", "Added by the developer in code"],
    ], { colW: [2.6, 2.4, 3.9, 3.23], fs: 14.5, highlight: 1, rowH: 0.7 });
  }
  {
    const s = add("Content", "Feature matrix", "●  built in      ◐  possible with libraries or effort      ○  not available");
    const Y = { text: "●", options: { color: HEX.ok, align: "center", fontSize: 16, bold: true } };
    const P = { text: "◐", options: { color: HEX.gold, align: "center", fontSize: 16, bold: true } };
    const N = { text: "○", options: { color: HEX.bad, align: "center", fontSize: 16 } };
    const rows = [["Agents as a language construct", Y, N, N, N, N, N, P, P], ["Budgets checked before running", Y, N, N, N, N, N, P, P],
      ["Human review / four-eyes", Y, P, P, P, P, P, P, P], ["Uncertainty as a type", Y, P, P, P, P, P, N, N],
      ["Fairness and robustness evals", Y, P, P, N, P, P, P, P], ["Signed, hash-chained audit", Y, P, P, P, P, P, P, P],
      ["Typed agent messages", Y, P, P, P, P, P, P, P], ["Contracts on every agent answer", Y, P, P, P, P, P, P, P],
      ["Governance diff between versions", Y, N, N, N, N, N, N, N], ["Quantum tools, verified", Y, P, P, P, P, P, N, N],
      ["General-purpose computing", N, Y, Y, Y, Y, Y, P, P], ["Mature ecosystem and community", N, Y, Y, Y, Y, Y, Y, Y],
      ["Raw performance", P, P, Y, Y, P, Y, P, P]].map((r) => r.map((c) => (typeof c === "object" ? { ...c, options: { ...c.options } } : c)));
    const hdr = ["Capability", "AlgoLang", "Python", "Java", "Rust", "TS", "Julia", "LangGraph", "CrewAI"];
    table(s, hdr, rows, { colW: [3.73, 1.15, 1.05, 1.05, 1.05, 1.05, 1.05, 1.0, 1.0], fs: 12.5, rowH: 0.36 });
    s.addNotes("Honest matrix: AlgoLang leads on governance features and trails on general-purpose computing, ecosystem maturity and raw performance.");
  }
  {
    const s = add("Content", "The same guarantee, two ways", "A budgeted agent with human review on low confidence");
    T(s, [B("Python with a framework"), { text: "   (sketch)", options: { color: MUTED } }], { x: 0.6, y: 1.75, w: 6, h: 0.4, fontSize: 16 });
    codeBox(s, `def triage(claim):
    if tokens_used() > 2000:
        raise BudgetError()
    out = llm.invoke(prompt(claim))
    score, conf = parse(out)
    log_audit(claim, out)    # remember to sign
    if conf < 0.8:
        queue_for_review(out) # remember to persist
    if "gender" in prompt(claim):
        ...                   # remember to check
    return score`, 0.6, 2.2, 6.0, 4.4, 12.5, "python sketch");
    T(s, [B("AlgoLang")], { x: 6.85, y: 1.75, w: 5, h: 0.4, fontSize: 16 });
    codeBox(s, `agent Triage(claim: text) -> uncertain<score> {
    goal   "Score {claim}"
    policy { budget tokens 2000
             require human when confidence < 0.8
             forbid gender }
}`, 6.85, 2.2, 5.88, 2.4, 12, "algolang triage");
    card(s, 6.85, 4.85, 5.88, 1.75, { fill: GOLDL, id: "enforced note" });
    T(s, [{ text: "Enforced, not remembered. ", options: { bold: true, color: NAVY } }, { text: "Budget, review queue, forbidden attribute and signed audit come from the language, in every program, every time." }],
      { x: 7.15, y: 4.85, w: 5.3, h: 1.75, fontSize: 16, valign: "middle" });
  }
  {
    const s = add("Content", "Where AlgoLang is not the right tool", "An honest view");
    const notFor = [["General computation", "No loops over numbers, no data structures beyond its types: write those as tools in Python or another language."],
      ["High-performance code", "The runtime is Python; speed comes from tools."],
      ["A young ecosystem", "One maintainer team, a small community and few third-party packages so far."]];
    for (let i = 0; i < 3; i++) {
      const y = 1.9 + i * 1.5;
      await iconDot(s, "FaXmark", 0.6, y + 0.1, 0.65, { fill: BAD, color: "FFFFFF", id: "limit " + (i + 1) });
      T(s, notFor[i][0], { x: 1.5, y, w: 4.9, h: 0.4, fontSize: 18, bold: true, color: NAVY });
      T(s, notFor[i][1], { x: 1.5, y: y + 0.42, w: 4.9, h: 0.9, fontSize: 15 });
    }
    card(s, 6.9, 1.9, 5.83, 4.7, { fill: NAVY, id: "use when" });
    T(s, "Use AlgoLang when", { x: 7.25, y: 2.15, w: 5.2, h: 0.5, fontSize: 22, bold: true, color: GOLD, fontFace: THEME.headFontFace });
    T(s, bullets(["AI agents make decisions that affect people or money", "You must show regulators who decided and why", "Fairness, budgets and human review are requirements, not wishes", "You want agent programs reviewed and tested like code"], { gap: 14 }),
      { x: 7.25, y: 2.85, w: 5.2, h: 3.6, fontSize: 17, color: WHITE });
  }

  // ═══ Section 4: Applications ═══
  sec("Applications");
  await divider("04", "22 enterprise applications", "Every one ships with policies, company tools, a knowledge base, evals, behaviour tests and system cards.", "FaLayerGroup");
  {
    const s = add("Content", "22 applications at a glance", "Open source in enterprise-apps/, each runnable offline");
    const stats = [["22", "applications"], ["38", "programs"], ["223", "programs on AlgoVM"], ["35", "compile checks"]];
    stats.forEach(([n, l], i) => {
      const x = 0.6 + i * 3.07;
      T(s, n, { x, y: 1.65, w: 2.85, h: 0.75, fontSize: 40, bold: true, color: GOLD, fontFace: THEME.headFontFace, align: "center" });
      T(s, l, { x, y: 2.38, w: 2.85, h: 0.3, fontSize: 13, color: MUTED, align: "center" });
    });
    for (let i = 0; i < 22; i++) {
      const a = APPS[i]; const col = i % 6, row = Math.floor(i / 6);
      const x = 0.6 + col * 2.035, y = 2.9 + row * 1.0;
      card(s, x, y, 1.92, 0.88, { fill: a[0] === "AI, markets & quantum" ? GOLDL : LIGHT, id: "tile " + a[1] });
      s.addImage({ data: await icon(a[4], HEX.navy), x: x + 0.12, y: y + 0.27, w: 0.34, h: 0.34, altText: a[2] });
      T(s, [{ text: a[2].replace(/ \(QuantOracle™\)/, "").replace(/^Algo\w+ /, "").replace(/™/g, ""), options: { bold: true, color: NAVY, breakLine: true } }, { text: a[3].split(/ · | for | & /)[0], options: { color: MUTED, fontSize: 10 } }],
        { x: x + 0.55, y: y + 0.06, w: 1.32, h: 0.76, fontSize: 11, valign: "middle", fit: "shrink" });
    }
    T(s, [{ text: "■ ", options: { color: "AFC0DA" } }, { text: "Enterprise operations & large-scale domains     " }, { text: "■ ", options: { color: GOLD } }, { text: "AI, markets & quantum" }],
      { x: 4.66, y: 6.62, w: 8.07, h: 0.25, fontSize: 11, color: MUTED, align: "right" });
  }
  const groups = { "Enterprise operations": "Enterprise operations", "AI, markets & quantum": "AI, markets & quantum", "Large-scale domains": "Large-scale domains" };
  let n = 0;
  for (let i = 0; i < 22; i += 2) {
    const g = APPS[i][0];
    const inGroup = APPS.filter((a) => a[0] === g);
    const k = inGroup.indexOf(APPS[i]);
    const pair = APPS[i + 1] && APPS[i + 1][0] === g ? [APPS[i], APPS[i + 1]] : [APPS[i]];
    const s = add("Content", `Applications · ${groups[g]}`, `${i + 1}${pair.length > 1 ? "–" + (i + 2) : ""} of 22   ·   enterprise-apps/${pair.map((p) => p[1]).join(", ")}`);
    for (let j = 0; j < pair.length; j++) await appCard(s, pair[j], 0.6 + j * 6.2, 1.75, 5.93, 5.05, i + j);
    if (pair.length === 1) i -= 1; // keep pairing aligned to groups
    n++;
    s.addNotes(pair.map((p) => `${p[2]} (${p[3]}): ${p[7]}`).join("\n"));
  }

  // ═══ Section 5: Platform ═══
  sec("Platform & roadmap");
  await divider("05", "Platform & roadmap", "A complete toolchain, and every planned release shipped one at a time.", "FaRoad");
  {
    const s = add("Content", "Toolchain", "Everything needed to write, test, ship and audit agent programs");
    codeBox(s, `$ pip install algolang
$ algo check app.algo
$ algo run app.algo --arg "claim=..." --stream
$ algo eval app.algo
$ algo card app.algo
$ algo build app.algo --ir --sign
$ algo mcp serve app.algo
$ algo pkg install insurance@^1.0`, 0.6, 1.8, 6.4, 3.45, 15, "cli commands");
    card(s, 0.6, 5.5, 6.4, 1.1, { fill: GOLDL, id: "offline note" });
    T(s, [B("Offline first.  "), { text: "Every command runs with the deterministic mock model; add a key and --live for real models." }], { x: 0.85, y: 5.5, w: 5.95, h: 1.1, fontSize: 15, valign: "middle" });
    const tc = [["FaTerminal", "CLI", "check, run, batch, eval, card, report, audit, evidence, build, pkg, mcp"],
      ["FaWindowMaximize", "Studio", "Browser IDE with review queue, dashboard, SSO and roles"],
      ["FaPython", "Python SDK", "Jupyter and Colab notebooks"], ["FaCode", "VS Code", "Extension and language server"],
      ["FaGithub", "CI", "Linux, macOS and Windows on every change"]];
    for (let i = 0; i < tc.length; i++) {
      const y = 1.8 + i * 0.98;
      await iconDot(s, tc[i][0], 7.35, y + 0.08, 0.66, { id: tc[i][1] + " icon" });
      T(s, tc[i][1], { x: 8.2, y: y + 0.02, w: 4.5, h: 0.38, fontSize: 17, bold: true, color: NAVY });
      T(s, tc[i][2], { x: 8.2, y: y + 0.4, w: 4.5, h: 0.45, fontSize: 14 });
    }
  }
  {
    const s = add("Content", "Roadmap delivered", "Every planned release shipped, one at a time");
    const R = [["v0.1", "Language"], ["v0.2", "Enterprise"], ["v0.3", "Uncertainty"], ["v0.3.4", "AlgoPulse"], ["v0.4", "Trustworthy AI"], ["v0.5", "Domain apps"], ["v0.6", "Quantum AI"], ["v0.7", "Interop"], ["v1.0", "Platform"], ["v1.1", "Accountable"]];
    const x0 = 1.0, x1 = 12.3, y = 3.0, step = (x1 - x0) / (R.length - 1);
    s.addShape(pres.shapes.LINE, { x: x0, y, w: x1 - x0, h: 0, line: { color: GOLD, width: 4 } });
    R.forEach(([v, t], i) => {
      const x = x0 + i * step, last = i === R.length - 1, d = last ? 0.55 : 0.38;
      s.addShape(pres.shapes.OVAL, { x: x - d / 2, y: y - d / 2, w: d, h: d, fill: { color: last ? GOLD : NAVY }, line: { color: WHITE, width: 2 }, objectName: "milestone " + v });
      T(s, v, { x: x - 0.7, y: y - 0.85, w: 1.4, h: 0.4, fontSize: last ? 20 : 17, bold: true, color: NAVY, align: "center" });
      T(s, t, { x: x - 0.7, y: y + 0.4, w: 1.4, h: 0.6, fontSize: 13, color: MUTED, align: "center" });
    });
    card(s, 0.6, 4.45, 5.95, 1.7, { fill: GOLDL, id: "latest" });
    T(s, [{ text: "Latest: 1.1", options: { bold: true, color: NAVY, fontSize: 20, breakLine: true } }, { text: "Agent contracts · what-if audits · governance diff, on the 1.0 platform (typed messages, AlgoVM, packages, SSO)." }],
      { x: 0.9, y: 4.45, w: 5.4, h: 1.7, fontSize: 16, valign: "middle" });
    card(s, 6.78, 4.45, 5.95, 1.7, { fill: NAVY, id: "after 1.1" });
    T(s, [{ text: "After 1.1", options: { bold: true, color: GOLD, fontSize: 20, breakLine: true } }, { text: "AlgoVM for browser and edge · organisation registries · federated review · long-running agents.", options: { color: WHITE } }],
      { x: 7.08, y: 4.45, w: 5.4, h: 1.7, fontSize: 16, valign: "middle" });
  }
  {
    const s = add("Content", "Getting started in five minutes", "Runs offline with the mock model; add a key and --live for real models");
    codeBox(s, `$ git clone https://github.com/drssnaiml1-cell/algolang
$ cd algolang && pip install -e .
$ algo run examples/hello.algo --arg "name=Asha"
$ algo studio`, 0.6, 1.8, 7.4, 2.0, 15, "quick start");
    const res = [["50", "sample programs", "with a PDF guide"], ["108", "page manual", "the language reference (PDF)"], ["22", "applications", "in enterprise-apps"]];
    res.forEach(([nn, l, d], i) => {
      const x = 0.6 + i * 2.5;
      card(s, x, 4.1, 2.3, 2.5, { id: "resource " + l });
      T(s, nn, { x, y: 4.4, w: 2.3, h: 0.75, fontSize: 36, bold: true, color: GOLD, align: "center", fontFace: THEME.headFontFace });
      T(s, [{ text: l, options: { bold: true, color: NAVY, breakLine: true } }, { text: d, options: { color: MUTED, fontSize: 12 } }], { x: x + 0.15, y: 5.25, w: 2.0, h: 1.1, fontSize: 15, align: "center" });
    });
    card(s, 8.3, 1.8, 4.43, 4.8, { fill: NAVY, id: "links" });
    T(s, "Find it", { x: 8.6, y: 2.05, w: 3.9, h: 0.5, fontSize: 22, bold: true, color: GOLD, fontFace: THEME.headFontFace });
    T(s, [
      { text: "Source", options: { bold: true, color: GOLD, breakLine: true } }, { text: "github.com/drssnaiml1-cell/algolang", options: { color: WHITE, breakLine: true } },
      { text: " ", options: { breakLine: true } },
      { text: "Website, playground, registry", options: { bold: true, color: GOLD, breakLine: true } }, { text: "drssnaiml1-cell.github.io/algolang", options: { color: WHITE, breakLine: true } },
      { text: " ", options: { breakLine: true } },
      { text: "Releases", options: { bold: true, color: GOLD, breakLine: true } }, { text: "Wheels for every version", options: { color: WHITE } },
    ], { x: 8.6, y: 2.7, w: 3.9, h: 3.7, fontSize: 15 });
  }

  // ═══ Section 6: Build with us ═══
  sec("Build with us");
  {
    const s = add("Content", "Build your application with AlgoLang", "Governed AI for your sector, from pilot to production");
    const offers = [["FaRocket", "Pilot", "A governed agent in one of your real workflows, with evals and an evidence pack."],
      ["FaIndustry", "Custom applications", "A sector application like the 22 shown here, built on your tools and policies."],
      ["FaChalkboardUser", "Training", "Teach teams and students to build and audit trustworthy agents."],
      ["FaFlask", "Research", "Joint papers and theses on agentic AI, XAI, AI governance and quantum AI."]];
    for (let i = 0; i < 4; i++) {
      const y = 1.8 + i * 1.22;
      await iconDot(s, offers[i][0], 0.6, y + 0.1, 0.75, { id: offers[i][1] + " icon" });
      T(s, offers[i][1], { x: 1.6, y: y + 0.02, w: 5.2, h: 0.4, fontSize: 18, bold: true, color: NAVY });
      T(s, offers[i][2], { x: 1.6, y: y + 0.44, w: 5.2, h: 0.65, fontSize: 15 });
    }
    card(s, 7.2, 1.8, 5.53, 4.85, { fill: NAVY, id: "contact card" });
    await iconDot(s, "FaEnvelope", 7.55, 2.15, 0.9, { fill: GOLD, color: HEX.navy, id: "contact icon" });
    T(s, "Applications & partnerships", { x: 8.65, y: 2.2, w: 3.9, h: 0.8, fontSize: 20, bold: true, color: WHITE, fontFace: THEME.headFontFace, valign: "middle" });
    T(s, [{ text: "cto@algoprofessor.com", options: { hyperlink: { url: "mailto:cto@algoprofessor.com" }, color: GOLD, bold: true } }],
      { x: 7.55, y: 3.3, w: 4.9, h: 0.65, fontSize: 28, fontFace: THEME.headFontFace });
    s.addShape(pres.shapes.LINE, { x: 7.55, y: 4.2, w: 4.83, h: 0, line: { color: "3A557E", width: 1 } });
    T(s, [
      { text: "Leadership  ", options: { color: LIGHT } }, { text: "ceo@algoprofessor.com", options: { color: WHITE, bold: true, hyperlink: { url: "mailto:ceo@algoprofessor.com" }, breakLine: true } },
      { text: "Web  ", options: { color: LIGHT } }, { text: "www.algoprofessor.com", options: { color: WHITE, bold: true, hyperlink: { url: "https://www.algoprofessor.com" }, breakLine: true } },
      { text: "Code  ", options: { color: LIGHT } }, { text: "github.com/drssnaiml1-cell/algolang", options: { color: WHITE, bold: true, hyperlink: { url: "https://github.com/drssnaiml1-cell/algolang" }, breakLine: true } },
      { text: "AlgoProfessor AI R&D Solutions, Hyderabad, India", options: { color: LIGHT } },
    ], { x: 7.55, y: 4.4, w: 4.9, h: 2.0, fontSize: 15, paraSpaceAfter: 6 });
    s.addNotes("For new applications, pilots and partnerships, contact cto@algoprofessor.com.");
  }
  {
    const s = add("Title", "Thank you", "Build AI people can trust, then prove it.");
    await iconDot(s, "FaCodeBranch", 0.8, 0.8, 1.0, { fill: GOLD, color: HEX.navy, id: "logo" });
    T(s, [{ text: "Dr. S. Satyanarayana, Ph.D., PDF (AI)", options: { bold: true, color: WHITE, breakLine: true } },
          { text: "Founder, CEO & Chief Agentic AI Scientist  ·  AlgoProfessor AI R&D Solutions, Hyderabad", options: { color: LIGHT } }],
      { x: 0.8, y: 4.75, w: 11, h: 0.8, fontSize: 16 });
    T(s, [{ text: "Applications: ", options: { color: LIGHT } }, { text: "cto@algoprofessor.com", options: { color: GOLD, bold: true, hyperlink: { url: "mailto:cto@algoprofessor.com" } } },
          { text: "     ·     github.com/drssnaiml1-cell/algolang", options: { color: GOLD } }],
      { x: 0.8, y: 6.1, w: 11.7, h: 0.45, fontSize: 16 });
  }

  await pres.writeFile({ fileName: OUT });
  if (SKILL) { const { applyTheme } = require(path.join(SKILL, "scripts/apply_theme.js")); await applyTheme(OUT, THEME); }
  console.log("wrote", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
