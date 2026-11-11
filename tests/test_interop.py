"""AlgoLang v0.7 Interoperability: argument types (E131), typed flow inputs, token-by-token streaming, flows
and agents served as MCP servers (stdio and HTTP), and the cost and energy dashboard."""
import io
import json
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import algocli_ext
import algolang as al
import algomcp
import algoruntime as rt
import algoserve
from algoc import CompileError, compile_source
from conftest import ROOT, write


def codes(src):
    with pytest.raises(CompileError) as e:
        compile_source(src, "t.algo")
    return [d.code for d in e.value.diags]


AGENTS = '''
agent Rate(s: score) -> text { goal "Explain the score {s}" }
agent Sum(items: list) -> text { goal "Summarise {items}" }
agent Judge(x: text) -> uncertain<score> { goal "Score {x}" }
agent Echo(x: text) -> text { goal "Repeat {x}" }
'''


# ─────────────────────────────── argument types ───────────────────────────────
def test_argument_types_are_checked_at_compile_time():
    ok = AGENTS + 'flow main(x: text, s: score, l: list) {\n j = Judge(x)\n emit Rate(j), Rate(s), Rate(0.4), Sum(l), Echo(j), Echo(l)\n}'
    compile_source(ok, "t.algo")
    assert "E131" in codes(AGENTS + 'flow main(x: text) { emit Rate(x) }')
    assert "E131" in codes(AGENTS + 'flow main(x: text) { emit Rate("high") }')
    assert "E131" in codes(AGENTS + 'flow main(x: text) { emit Sum(x) }')
    assert "E131" in codes(AGENTS + 'flow main(x: text) { emit Rate(s = x) }')
    assert "E131" in codes(AGENTS + 'flow main(x: text) { e = Echo(x)\n emit Rate(e) }')


@pytest.mark.parametrize("typ,raw,want", [("score", "0.8", 0.8), ("score", "80%", 0.8), ("bool", "yes", True),
                                          ("list", "a; b ; c", ["a", "b", "c"]), ("list", '["x", "y"]', ["x", "y"]),
                                          ("list", "a, b", ["a", "b"]), ("json", '{"k": 1}', {"k": 1}),
                                          ("text", ["a", "b"], '["a", "b"]')])
def test_flow_inputs_are_converted_to_their_types(typ, raw, want):
    assert rt.coerce_input("main", "x", typ, raw) == want


@pytest.mark.parametrize("typ,raw", [("score", "high"), ("score", "1.5"), ("bool", "maybe"), ("json", "{oops")])
def test_bad_flow_inputs_are_refused(typ, raw):
    with pytest.raises(rt.InputTypeError):
        rt.coerce_input("main", "x", typ, raw)


def test_sdk_runs_with_typed_inputs(project):
    p = al.compile(AGENTS + 'flow main(l: list, s: score) {\n r = par for it in l { Echo(it) }\n emit r, Rate(s)\n}', "t")
    res = p.run(l="alpha; beta; gamma", s="0.7")
    assert res.ok and len(res.values[0]) == 3
    bad = p.run(l="a", s="very high")
    assert bad.status == "failed" and "must be a score" in bad.problem


# ─────────────────────────────── streaming ───────────────────────────────
def test_value_stream_extracts_the_value_as_it_arrives():
    got = []
    vs = rt.ValueStream(got.append)
    for chunk in ['{"val', 'ue": "Hel', 'lo \\"wo', 'rld\\" \\u00e9', '\\n!", "confidence": 0.9}']:
        vs.feed(chunk)
    assert "".join(got) == 'Hello "world" é\n!'


def test_on_token_streams_every_agent(project):
    events = []
    p = al.compile(AGENTS + 'flow main(x: text) { a = Echo(x)\n emit a, Judge(x) }', "t")
    res = p.run(x="streaming works", on_token=events.append)
    assert res.ok
    echo = [e for e in events if e["agent"] == "Echo"]
    assert echo[0]["type"] == "start" and echo[-1]["type"] == "end"
    assert "".join(e["text"] for e in echo if e["type"] == "delta") == res.values[0]
    judge_end = [e for e in events if e["agent"] == "Judge" and e["type"] == "end"]
    assert judge_end and isinstance(judge_end[0]["value"], float)


def test_claude_backend_streams_with_the_messages_stream_api():
    chunks = ['{"value": "Par', 'is is the ', 'capital", "confidence": 0.93}']

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        text_stream = iter(chunks)

        def get_final_message(self):
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="".join(chunks))],
                                         usage=types.SimpleNamespace(input_tokens=10, output_tokens=8), stop_reason="end_turn")

    client = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: Stream(),
                                                                   create=lambda **kw: pytest.fail("not streamed")))
    spec = rt.AgentSpec(name="Geo", params=[], returns="text", role="", goal="capital?", uses=[], model="m", policy={})
    got = []
    tok = rt.STREAM.set(got.append)
    try:
        val, conf, tokens, _calls = rt.ClaudeBackend(client).complete(spec, "m", "capital?", "capital?")
    finally:
        rt.STREAM.reset(tok)
    assert val == "Paris is the capital" and "".join(got) == val and tokens == (10, 8)


def test_local_backend_streams_server_sent_events():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["stream"] is True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for part in ['{"value": "small ', 'models ', 'stream", "confidence": 0.8}']:
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': part}}]})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        be = rt.LocalBackend({"base_url": f"http://127.0.0.1:{srv.server_port}/v1"})
        spec = rt.AgentSpec(name="S", params=[], returns="text", role="", goal="g", uses=[], model="local:x", policy={})
        got = []
        tok = rt.STREAM.set(got.append)
        try:
            out = be.complete(spec, "local:x", "g", "g")
        finally:
            rt.STREAM.reset(tok)
        assert out[0] == "small models stream" and "".join(got) == out[0]
    finally:
        srv.shutdown()


# ─────────────────────────────── MCP server ───────────────────────────────
SERVED = '''// Answers questions about a city.
risk limited "Answering questions for residents"
disclose "Answers are written with the help of an AI system."
agent Answer(question: text, urgency: score) -> text {
    goal "Answer {question} with urgency {urgency}"
}
agent Classify(question: text) -> list { goal "Topics in {question}" }
flow main(question: text, urgency: score) {
    emit Answer(question, urgency)
}
flow topics(question: text) {
    emit Classify(question)
}
'''


def test_flow_server_lists_typed_tools_and_runs_flows(project):
    write(project / "city.algo", SERVED)
    srv = algoserve.FlowServer([str(project / "city.algo")], agents=True)
    init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["capabilities"]["tools"] is not None
    tools = {t["name"]: t for t in srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert {"city_main", "city_topics", "city_agent_Answer", "city_agent_Classify"} <= set(tools)
    sch = tools["city_main"]["inputSchema"]
    assert sch["properties"]["urgency"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert sch["required"] == ["question", "urgency"] and "limited risk" in tools["city_main"]["description"]
    r = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "city_main", "arguments": {"question": "When is bin day?", "urgency": 0.3}}})["result"]
    assert not r["isError"] and r["structuredContent"]["status"] == "ok" and "When is bin day" in r["content"][0]["text"]
    bad = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                      "params": {"name": "city_main", "arguments": {"question": "q", "urgency": "very"}}})["result"]
    assert bad["isError"] and "must be a score" in bad["content"][0]["text"]
    ag = srv.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                     "params": {"name": "city_agent_Classify", "arguments": {"question": "parking and parks"}}})["result"]
    assert isinstance(ag["structuredContent"]["values"][0], list)
    assert srv.handle({"jsonrpc": "2.0", "id": 6, "method": "nope"})["error"]["code"] == -32601


def test_stdio_server_sends_progress_notifications(project):
    write(project / "city.algo", SERVED)
    srv = algoserve.FlowServer([str(project / "city.algo")])
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "city_main", "arguments": {"question": "Is the library open on Sunday?", "urgency": 0.5},
                "_meta": {"progressToken": "t1"}}}]
    out = io.StringIO()
    srv.serve_stdio(io.StringIO("\n".join(json.dumps(m) for m in msgs) + "\n"), out)
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    prog = [m for m in lines if m.get("method") == "notifications/progress"]
    final = [m for m in lines if m.get("id") == 2][0]
    assert prog and all(p["params"]["progressToken"] == "t1" for p in prog)
    assert final["result"]["structuredContent"]["status"] == "ok"


def test_an_algolang_program_calls_another_algolang_program_over_mcp(project):
    """Interoperability end to end: program B uses program A's flow as an MCP tool (stdio subprocess)."""
    write(project / "city.algo", SERVED)
    cfg = {"mcp_servers": {"city": {"command": "{python}", "args": [str(ROOT / "algoc.py"), "mcp", "serve",
                                                                    str(project / "city.algo")]}}}
    write(project / "algo.config.json", json.dumps(cfg))
    rt._CONFIG = None
    rt.load_config(reload=True)
    try:
        b = al.compile('tool city.city_main from mcp "city"\n'
                       'agent Desk(q: text) -> text { goal "Help with {q}"  uses city.city_main }\n'
                       'flow main(q: text) { emit Desk(q) }\n', "desk")
        res = b.run(q="Where do I renew a parking permit?")
        tool_text = res.calls[0]["tool_calls"][0]
        assert res.ok and tool_text["tool"] == "city.city_main" and tool_text["chars"] > 0
    finally:
        algomcp.close_all()


def test_http_transport_and_bearer_token(project, monkeypatch):
    write(project / "city.algo", SERVED)
    monkeypatch.setenv("ALGO_MCP_TOKEN", "s3cret")
    httpd = algoserve.FlowServer([str(project / "city.algo")]).http_server("127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/mcp"
    try:
        c = algomcp.HttpClient("city", {"url": url, "headers": {"Authorization": "Bearer s3cret"}})
        c.initialize()
        assert "city_topics" in c.tools()
        assert "Topics in" in c.call("city_topics", {"question": "parking"}) or "item" in c.call("city_topics", {"question": "parking"})
        bad = algomcp.HttpClient("city", {"url": url})
        with pytest.raises(Exception):
            bad.initialize()
    finally:
        httpd.shutdown()


# ─────────────────────────────── dashboard ───────────────────────────────
def test_cost_and_energy_dashboard(project):
    write(project / "city.algo", SERVED)
    al.load(project / "city.algo").run(question="Bin day?", urgency=0.2)
    rep = al.audit.report(str(project / "runs"))
    html = algocli_ext.dashboard_html(rep)
    assert "Cost by program" in html and "city" in html and "QPU time" in html
    out = project / "dash.html"
    assert algocli_ext.cmd_report(str(project / "runs"), html_out=str(out)) == 0 and out.exists()


def test_cli_stream_flag_prints_tokens(project, capsys, monkeypatch):
    monkeypatch.setenv("ALGO_STREAM", "1")
    write(project / "city.algo", SERVED)
    p = al.load(project / "city.algo")
    p.run(question="Library hours?", urgency=0.1, on_token=rt._print_stream)
    assert "✎ Answer:" in capsys.readouterr().out
