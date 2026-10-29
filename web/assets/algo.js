// Shared helpers for the AlgoLang website: syntax highlighting and copy buttons.
(function (g) {
  const KW = new Set("agent flow model tool use pack as policy role goal uses model budget tokens retry timeout require human when confidence forbid cache par for in if else emit seconds".split(" "));
  const TY = new Set("text score list json bool".split(" "));
  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const RX = /(\/\/[^\n]*)|("(?:[^"\\\n]|\\.)*"?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z_0-9]*)|([\s\S])/g;
  function highlight(src) {
    let out = "", m;
    RX.lastIndex = 0;
    while ((m = RX.exec(src))) {
      if (m[1]) out += `<span class="c">${esc(m[1])}</span>`;
      else if (m[2]) out += `<span class="s">${esc(m[2])}</span>`;
      else if (m[3]) out += `<span class="n">${m[3]}</span>`;
      else if (m[4]) out += KW.has(m[4]) ? `<span class="k">${m[4]}</span>` : TY.has(m[4]) ? `<span class="t">${m[4]}</span>` : m[4];
      else out += esc(m[5]);
    }
    return out;
  }
  function copy(text, btn) {
    const done = () => { if (btn) { const t = btn.textContent; btn.textContent = "Copied"; setTimeout(() => (btn.textContent = t), 1400); } };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done); else done();
  }
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-copy]");
    if (b) copy(b.getAttribute("data-copy"), b);
  });
  g.AlgoSite = { highlight, esc, copy };
})(window);
