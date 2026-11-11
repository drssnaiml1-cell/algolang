# v0.7 Interoperability examples

`city_help.algo` is an ordinary governed AlgoLang program. v0.7 lets other software use it as a tool.

**Serve it over MCP** (stdio, for Claude Desktop, IDEs and other agents):

```bash
algo mcp serve examples/v07/city_help.algo            # tools: city_help_main, city_help_batch
algo mcp serve examples/v07/city_help.algo --agents   # also city_help_agent_Topics, city_help_agent_Answer
algo mcp serve examples/v07/city_help.algo --http 8765   # Streamable HTTP on 127.0.0.1:8765/mcp (ALGO_MCP_TOKEN for a bearer token)
```

Claude Desktop (`claude_desktop_config.json`):

```json
{"mcpServers": {"city-help": {"command": "algo", "args": ["mcp", "serve", "/path/to/examples/v07/city_help.algo"]}}}
```

The tool input schemas come from the flows' types: `urgency: score` becomes a number between 0 and 1, and `questions: list` becomes an array. Results return the run status, the emitted values, anything escalated for human review, the cost and the audit file.

**Call it from another AlgoLang program** over the same protocol:

```algo
tool city.city_help_main from mcp "city"      // "mcp_servers": {"city": {"command": "algo", "args": ["mcp", "serve", "city_help.algo"]}}
agent Concierge(q: text) -> text { goal "Help a visitor with {q}"  uses city.city_help_main }
```

**Watch the agents write** (token by token):

```bash
algo run examples/v07/city_help.algo --stream --arg "question=When is bulky waste collected in Ward 12?" --arg urgency=0.4
algo run examples/v07/city_help.algo --flow batch --arg "questions=Bin day?; Library hours?; Property tax due date?"
```

**Types are checked** at compile time (E131) and at the door: `--arg urgency=high` is refused with
`flow main: input 'urgency' must be a score between 0 and 1`.

**Cost and energy dashboard:** `algo report runs --html dashboard.html`, or open `/dashboard` in Studio.
