# Browsing a corpus with mcpdoc

`mcpdoc` serves llms.txt files as an MCP documentation server. Use this after
`references/llms-txt-discovery.md` has produced a real corpus URL — mcpdoc does not discover
anything, it only wraps known URLs.

Prerequisites: `uvx` (mcpdoc) and `npx` (mcporter). No API keys.

## Start a server

```bash
uvx --from mcpdoc mcpdoc \
    --urls "LangGraph:https://langchain-ai.github.io/langgraph/llms.txt" \
           "LangChain:https://python.langchain.com/llms.txt" \
    --transport sse --port 8082
```

| Flag | Default | Meaning |
|---|---|---|
| `--urls` | required | one or more `Name:URL` llms.txt sources |
| `--transport` | `stdio` | `stdio` or `sse` |
| `--host` | `127.0.0.1` | SSE bind address; localhost only by default |
| `--port` | `8000` | SSE port |
| `--allowed-domains` | per-source host | extra domains to fetch from; `'*'` disables the allowlist |
| `--follow-redirects` | false | needed for hosts that redirect `llms-full.txt` |
| `--timeout` | `10.0` | per-request HTTP timeout, seconds |
| `--yaml` / `--json` | — | load sources from a config file |

## Query it

```bash
npx mcporter list --http-url "http://localhost:8082/sse"
npx mcporter call --http-url "http://localhost:8082/sse" list_doc_sources --output json
npx mcporter call --http-url "http://localhost:8082/sse" fetch_docs \
    url="https://langchain-ai.github.io/langgraph/llms.txt" --output json | jq -r '.content[].text'
```

Two tools: `list_doc_sources()` and `fetch_docs(url)`. The flow is index → pick a page URL →
fetch that page. `fetch_docs` only returns URLs inside the allowed domains.

Run it detached with `&>/tmp/mcpdoc.log &` when the reads will span several turns; kill the port
when done rather than leaving it up.

## Source config files

```yaml
# ~/mcpdoc-sources.yaml
sources:
  - name: LangGraph
    llms_txt: https://langchain-ai.github.io/langgraph/llms.txt
    description: LangGraph Python documentation
```

```bash
uvx --from mcpdoc mcpdoc --yaml ~/mcpdoc-sources.yaml --transport sse --port 8082
```

JSON equivalent uses `{"sources": [{"name": ..., "llms_txt": ...}]}`.

## Register it natively (needs a gateway restart — operator's call)

```yaml
mcp:
  servers:
    mcpdoc-langchain:
      transport: sse
      url: http://localhost:8082/sse
```

Prefer the ad-hoc `--http-url` path: it is per-repo, needs no config edit, and no restart.

## Known sources

Grab the real corpus URL from the target site first — several of these commonly cited paths are
stale or served as HTML. Treat this list as candidates to validate, not as truth.

- LangChain ecosystem: `langchain-ai.github.io/langgraph/llms.txt`, `python.langchain.com/llms.txt`,
  `langchain-ai.github.io/langgraphjs/llms.txt`, `js.langchain.com/llms.txt`
- Frameworks: `fastapi.tiangolo.com/llms.txt`, `react.dev/llms.txt`, `nextjs.org/llms.txt`,
  `vuejs.org/llms.txt`
- Infra / data: `docs.docker.com/llms.txt`, `git-scm.com/llms.txt`, `postgresql.org/docs/llms.txt`,
  `techdocs.akamai.com/llms.txt`

## Troubleshooting

| Issue | Fix |
|---|---|
| `Domain not allowed` | add `--allowed-domains '*'` |
| Connection refused | check host/port, confirm mcpdoc is running |
| Empty results | corpus may be HTML shell or malformed — validate per discovery gate |
| Timeouts | raise `--timeout 30` |
| Redirect loop / empty body | add `--follow-redirects` |

Browsing a repo's own docs is usually faster through DeepWiki/GitMCP (see the main workflow);
reach for mcpdoc when you want an entire third-party doc site addressable over MCP.
