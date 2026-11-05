---
name: github-qa-retrieval
description: Use when QA-ing a GitHub repo or an llms.txt doc corpus.
version: 1.4.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [MCP, Documentation, GitHub, QA, Retrieval, Code-Understanding, llms-txt, Discovery]
    related_skills: [mcporter, native-mcp, searxng-search]
prerequisites:
  commands: [npx]
  note: mcporter is invoked via npx, no global install required
---

# GitHub QA Retrieval Skill

> **Dependencies**: Node.js with `npx` (no global install needed — mcporter auto-installs on first run)

## ⚠️ `gh repo qa` DOES NOT EXIST

There is no `gh repo qa` subcommand. There never was. Do not call it.

It is a dangerous invented command because **it does not error**: gh parses
`repo` as the subcommand and treats `qa` as a trailing arg, falling through to
`gh repo --help` — which prints ordinary repository help and exits **0**. That
false success is why models assume the command works and start inventing
arguments (`gh repo qa "owner/repo"`, `gh repo qa --json`, ...) instead of
loading this skill.

**The task this command pretends to do is what THIS SKILL does** — repo QA and
documentation retrieval via DeepWiki/GitMCP over `mcporter`. Go straight to the
Workflow section below.

### Enforcement: the `gh` shim

A PATH shim intercepts the mistake and forces a read of this file:

- **Shim:** `scripts/gh-shim.sh`, alongside this file in the installed skill directory
- **Install:** put a symlink to it earlier on PATH than the real `gh` (see the portable instructions below)
- **Intercepts:** `gh repo qa …` → prints a hard-failure banner + the entire SKILL.md to stderr, `exit 1`
- **Everything else** execs through to the real `gh` binary unchanged (default `/usr/bin/gh`; override with `GH_SHIM_REAL_GH`)
- **Log:** `${HERMES_HOME:-$HOME/.hermes}/logs/gh-qa-shim.log` (timestamp, cwd, args); set `HERMES_HOME` to choose another base directory

Install the optional shim after the skill is installed. Set `SKILL_DIR` to the
actual directory containing this `SKILL.md`, then link it somewhere earlier on
PATH than the real `gh`:

```bash
SKILL_DIR=/path/to/github-qa-retrieval
mkdir -p "$HOME/.local/bin"
ln -sfn "$SKILL_DIR/scripts/gh-shim.sh" "$HOME/.local/bin/gh"
```

The shim resolves `SKILL.md` relative to its own symlink-resolved location, so
it works across skill directories and platforms with Bash. Its log defaults to
`${HERMES_HOME:-$HOME/.hermes}/logs/gh-qa-shim.log`; set `HERMES_HOME` to use a
different base. Set `GH_SHIM_REAL_GH` if the real binary is not `/usr/bin/gh`.

**If you are reading this because a `gh repo qa` command just failed:** good —
that was the shim working. Do not retry the command. Use the Workflow section
below.

**First-line documentation retrieval for codebases.** Use this skill BEFORE manually reading code files via MCP.

## Documentation corpora: llms.txt / llms-full.txt

A growing share of doc sites publish themselves as a single Markdown file. That is cheaper and
cleaner than crawling, so check for it before scraping anything.

| Need | Go to |
|---|---|
| Find a corpus for a domain / org / topic | `references/llms-txt-discovery.md` |
| Serve a corpus you already found as an MCP doc server | `references/mcpdoc-browsing.md` |
| Search-operator syntax (`site:`, `filetype:`, `inurl:`) per engine | skill `searxng-search` |

Discovery order is probe → dork → GitHub filename sweep → registries: the path is fixed, so
request `/llms.txt` and `/llms-full.txt` directly instead of searching for them. **HTTP 200 is not
proof** — HTML shells, redirect-to-index, and 401-byte page-not-found shims all answer 200.

## Philosophy

When you need to understand a repository, use this skill first. It queries multiple free MCP documentation servers in parallel to get:
- High-level architecture overview
- API documentation and usage patterns
- Code examples and common workflows
- Recent changes and gotchas

Only fall back to `read_file`, `browser_navigate`, or `mcp_*` native tools if the QA retrieval is insufficient.

## Workflow

```
User asks about repo/code ──► github-qa-retrieval skill ──► Parallel MCP queries
                                                    ──► Aggregated answer
                                                    ──► [If insufficient] ──► Manual code reading
```

## MCP Servers Used

| Server | Source | Free Tier | Auth | Rate Limits | Best For |
|--------|--------|-----------|------|-------------|----------|
| DeepWiki | `https://mcp.deepwiki.com/mcp` | Unlimited | None | **Aggressive** (hits immediately) | Architecture docs, how-to questions |
| GitMCP | `https://gitmcp.io/{owner}/{repo}` | Unlimited | None | Unknown (Cloudflare) | Per-repo docs, code search, examples |
| Mintlify | `https://{subdomain}.mintlify.app/mcp` | 200/hr/user, 1K/hr/site | None | Documented | Mintlify-hosted docs |
| GitHub MCP | `https://api.githubcopilot.com/mcp/` | Requires PAT | GitHub PAT | GitHub API limits | File contents, issues, PRs |

### About Mintlify API Keys
**No API key required** for public Mintlify documentation sites. Just use the URL pattern:
```
https://{your-subdomain}.mintlify.app/mcp
```

Private/restricted docs may require authentication via dashboard settings.

### DeepWiki Rate Limit Reality
Rate limits exist but are **not as aggressive as previously documented**. In testing (Apr 2026), DeepWiki queries succeeded without rate limiting. Still, have GitMCP fallback ready — limits may apply under heavy usage or for unindexed repos.

## Quick Reference

### Using mcporter (via npx)

```bash
# mcporter auto-installs via npx — no global install needed
npx mcporter --version

# List tools for a server
npx mcporter list --http-url "https://gitmcp.io/owner/repo"
```

### DeepWiki Query
```bash
# ⚠️ Parameter is repoName (camelCase), NOT repo_name (snake_case)
npx mcporter call --http-url "https://mcp.deepwiki.com/mcp" \
  ask_question \
  repoName="NousResearch/hermes-agent" \
  question="How does the skill system work?" \
  --output json
```

**⚠️ Parameter gotcha:** `ask_question` uses `repoName` (camelCase). Using `repo_name` will fail with "Missing required argument [repoName]" / "Unexpected keyword argument [repo_name]".

DeepWiki also has:
- `read_wiki_structure(repoName)` — list all doc topics for a repo
- `read_wiki_contents(repoName)` — view full generated docs

### GitMCP Ad-Hoc Mode (Recommended)
```bash
# Use --http-url for zero-config per-repo queries
npx mcporter call \
  --http-url "https://gitmcp.io/NousResearch/hermes-agent" \
  <tool-name> \
  --output json
```

**GitMCP Tool Name Pattern:** `{server_prefix}.{tool}` where prefix is derived from URL path:
- `fetch_hermes_agent_documentation` (not just `fetch_documentation`)
- `search_hermes_agent_documentation`
- `search_hermes_agent_code`
- `fetch_generic_url_content`

### GitMCP Code Search
```bash
# Discover actual tool names first
npx mcporter list --http-url "https://gitmcp.io/NousResearch/hermes-agent"

# Then call with full tool name
npx mcporter call \
  --http-url "https://gitmcp.io/NousResearch/hermes-agent" \
  search_hermes_agent_code \
  query="sharegpt OR trajectory" \
  --output json
```

### Fetch Raw Documentation Files
```bash
# Use fetch_generic_url_content for raw GitHub files
npx mcporter call \
  --http-url "https://gitmcp.io/NousResearch/hermes-agent" \
  fetch_generic_url_content \
  url="https://raw.githubusercontent.com/owner/repo/main/docs/file.md" \
  --output json
```

## GitMCP Tool Reference

When querying `gitmcp.io/{owner}/{repo}`, available tools are:

| Tool | Purpose |
|------|---------|
| `{prefix}_documentation()` | Fetch llms.txt / generated docs |
| `search_{prefix}_documentation(query)` | Semantic search in docs |
| `search_{prefix}_code(query, page?)` | GitHub code search |
| `fetch_generic_url_content(url)` | Fetch any raw URL |

**Discover prefix:** Run `npx mcporter list --http-url "https://gitmcp.io/owner/repo"` to see actual tool names.

## Aggregated Query Pattern with Fallback

```bash
#!/bin/bash
# Query DeepWiki first, fall back to GitMCP on failure

REPO="NousResearch/hermes-agent"
QUERY="How does trajectory export work?"

# Try DeepWiki (will likely rate limit)
npx mcporter call deepwiki.ask_question \
  repo="$REPO" \
  query="$QUERY" \
  --output json > /tmp/result.json 2>/dev/null || \
\
# Fallback to GitMCP
echo "DeepWiki rate limited, using GitMCP..." && \
npx mcporter call \
  --http-url "https://gitmcp.io/$REPO" \
  "search_${REPO//\//_}_code" \
  query="trajectory export" \
  --output json > /tmp/result.json

cat /tmp/result.json
```

## Decision Tree

```
Need to understand code?
    │
    ▼
┌─────────────────────────────────────┐
│ Try github-qa-retrieval skill first │
│ 1. DeepWiki for "how does X work?" │
│ 2. GitMCP for finding specific files│
└─────────────────────────────────────┘
    │
    ├─► Got comprehensive answer? ──► Done
    │
    ├─► DeepWiki rate limited?
    │   └─► Fall back to GitMCP code search + raw URL fetch
    │
    └─► Need exact code, not summaries?
        │
        ▼
    ┌─────────────────────────────────┐
    │ GitMCP fetch_generic_url_content│
    │ or manual read_file/scrapling  │
    └─────────────────────────────────┘
```

## When to Use This Skill

✅ **USE THIS SKILL FIRST** for:
- Understanding project structure and architecture
- Learning how to use/configure a library
- Finding examples and usage patterns
- Understanding recent changes or deprecations
- Getting context before diving into source code

❌ **SKIP TO MANUAL READING** if:
- You need exact line-by-line code analysis
- You're debugging a specific bug (need precise file/line)
- The repo is private and not indexed by DeepWiki/GitMCP
- You need to see recent uncommitted changes

## Rate Limit Survival Patterns

### Pattern 1: DeepWiki First (AI-Synthesized Answers)
```bash
# DeepWiki gives the best answers for "how does X work?" questions
# ~18s but comprehensive AI-synthesized response
npx mcporter call --http-url "https://mcp.deepwiki.com/mcp" \
  ask_question \
  repoName="owner/repo" \
  question="your question" \
  --output json
```

### Pattern 2: GitMCP for Speed (Code Search + Raw Fetch)
```bash
# ~7s for code search, ~12s for docs. Faster but more targeted.
# Discover tools first
npx mcporter list --http-url "https://gitmcp.io/owner/repo"

# Code search (returns file paths + URLs)
npx mcporter call --http-url "https://gitmcp.io/owner/repo" \
  search_hermes_agent_code \
  query="your search" \
  --output json

# Fetch specific raw files (fastest for known paths)
npx mcporter call --http-url "https://gitmcp.io/owner/repo" \
  fetch_generic_url_content \
  url="https://raw.githubusercontent.com/owner/repo/main/docs/file.md" \
  --output json
```

### Pattern 3: When Both Fail or Are Rate Limited
```bash
# Fall back to web_extract on raw GitHub URLs (no MCP needed)
# Or use the stealth-extraction-escalator skill for GitHub browse pages
```

## Examples

### Understanding a Repository Without Reading Code
```bash
# 1. Get high-level docs
npx mcporter call \
  --http-url "https://gitmcp.io/NousResearch/hermes-agent" \
  fetch_hermes_agent_documentation \
  --output json | jq -r '.content[].text' | head -100

# 2. Search for specific feature
npx mcporter call \
  --http-url "https://gitmcp.io/NousResearch/hermes-agent" \
  search_hermes_agent_code \
  query="trajectory sharegpt" \
  --output json

# 3. Fetch the trajectory format documentation
npx mcporter call \
  --http-url "https://gitmcp.io/NousResearch/hermes-agent" \
  fetch_generic_url_content \
  url="https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/developer-guide/trajectory-format.md" \
  --output json
```

### Comparing Multiple Repositories
```bash
# Query multiple repos for comparison
for REPO in "langchain-ai/langchain" "run-llama/llama_index"; do
  PREFIX=$(echo "$REPO" | tr '/' '_')
  npx mcporter call \
    --http-url "https://gitmcp.io/$REPO" \
    "search_${PREFIX}_code" \
    query="RAG implementation" \
    --output json > "/tmp/${PREFIX}_rag.json" &
done
wait
```

## Error Handling

| Error | Meaning | Fallback |
|-------|---------|----------|
| "Rate limited" (DeepWiki) | Expected on 1st/2nd query | Use GitMCP immediately |
| "Tool not found" | Wrong tool name | Run `npx mcporter list --http-url ...` to discover names |
| "Repo not found" | Private repo | Use GitHub MCP with PAT |
| "Empty results" | Query too specific | Broaden query or fetch raw docs |
| "Connection failed" | Network/MCP issue | Retry or use manual reading |

## Configuration (Optional)

### Add DeepWiki to mcporter (if it ever works)
```bash
npx mcporter config add deepwiki --url "https://mcp.deepwiki.com/mcp"
```

### Add GitHub MCP (for private repos)
```bash
npx mcporter config add github \
  --url "https://api.githubcopilot.com/mcp/" \
  --header "Authorization: Bearer $GITHUB_PAT"
```

## Integration with Hermes

This skill is designed to be called via `execute_code` with terminal commands, keeping the MCP interaction explicit and controllable. Results are then fed into the conversation context before deciding on further tool use.

**Key insight from practice:** DeepWiki works well for AI-synthesized answers (~18s, comprehensive). GitMCP is faster for targeted searches (~7-12s) and raw file fetches. **Neither hit rate limits in testing** (Apr 2026), but have the other as fallback. Always use `--http-url` with mcporter for zero-config queries. Critical gotcha: DeepWiki uses `repoName` (camelCase), not `repo_name`.

**Remember**: This is your first-line tool. Only reach for manual file reading when the QA layer doesn't provide sufficient detail.

## When to Delegate Research

When you need to query multiple repos, fetch many raw files, or do extended documentation excavation that will produce large intermediate outputs, **use `delegate_task`** to keep the research out of your main context. The subagent can run multiple mcporter calls, aggregate the findings, and return only the synthesized result. This prevents context window exhaustion from raw MCP responses, code file dumps, and repetitive query outputs.

Rule of thumb: if you're making 3+ mcporter calls in sequence for a single research question, or the combined output will exceed ~5000 chars of raw data, delegate it.
