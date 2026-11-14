---
name: github-qa-retrieval
description: Use when QA-ing GitHub repos or llms.txt corpora.
version: 2.2.0
author: gwyntel
license: MIT
metadata:
  hermes:
    tags: [MCP, Documentation, GitHub, QA, Retrieval, Code-Understanding, Code-Search, ripgrep, ast-grep, Subagent]
    related_skills: [mcporter, native-mcp, searxng-search]
prerequisites:
  commands: [npx]
  note: mcporter runs via npx. Optional mcpdoc browsing uses uvx. Raw code search tools are local-first.
---

# GitHub QA Retrieval Skill

> **Dependencies**: Node.js with `npx` (no global install needed — mcporter auto-installs on first run).
> Local code search uses `rg` / `git` / `fd`, which ship with most developer images. Degrade gracefully if missing (see §3.11).

---

## 0. The non-negotiable rules (read these first)

| # | Rule | Why |
|---|------|-----|
| R1 | **`gh repo qa` is not a `gh` subcommand — the PATH shim intercepts it and prints this skill.** | If the banner appears you already have the instructions: go to §3 instead of retrying the command. |
| R2 | **Raw code searching runs in a blocking subagent** (`delegate_task`), not inline. | 3+ raw searches dump 10k–80k chars into your context and you lose the thread. |
| R3 | **Never answer a code question from memory when a search is cheap.** | Invented file paths and APIs are the #1 QA failure mode. |
| R4 | **Every factual claim about code carries `path:line`.** | Unattributed claims are treated as guesses and must be re-verified. |
| R5 | **Fixed order: documentation search → indexed code search → raw local search.** Raw `rg`/`grep` is the last resort, never the opening move. | Docs are pre-indexed and cheap; local search is expensive and floods context. Truth still needs `path:line` — tier 2 supplies paths, tier 3 supplies exact lines. |
| R6 | **Delegate when a question needs 3+ retrieval calls or more than ~5000 chars of raw output — and always delegate raw/local shell searches, however small.** | The threshold governs non-raw work; raw shell search is never inline (§2.1). |

---

## 1. `gh repo qa` is not a command — the shim says so for you

`gh repo qa …` is not a `gh` subcommand. `gh` parses `repo` as the subcommand and treats `qa` as
a trailing argument, so it prints `gh repo --help` and exits **0** — a false success that made
agents invent arguments for a command that was never real. The work that imaginary command
promised is the work §3 does.

The guardrail is already in place: the `gh` shim (`scripts/gh-shim.sh`, §8) catches the call at
the shell boundary, prints a one-line correction plus this file to stderr, logs it, and exits `1`.
Every other `gh` invocation passes through to the real binary unchanged.

**You do not have to police yourself against this command** — if you invoke it, the shim hands
you the instructions. Mechanics, for reference:

- **Shim:** `scripts/gh-shim.sh`, alongside this file in the installed skill directory
- **Install:** put a symlink to it earlier on PATH than the real `gh` (see §8)
- **Intercepts:** `gh repo qa …` → correction banner + the entire SKILL.md on stderr, `exit 1`
- **Everything else** execs through to the real `gh` binary unchanged (default `/usr/bin/gh`; override with `GH_SHIM_REAL_GH`)
- **Log:** `${HERMES_HOME:-$HOME/.hermes}/logs/gh-qa-shim.log` (timestamp, cwd, args)

---

## 2. Architecture: three tiers, documentation first

**The order is fixed. Do not reorder it per question.**

| Tier | Layer | Tools | Cost |
|------|-------|-------|------|
| **1** | **Documentation search** | `llms.txt` corpus / mcpdoc · DeepWiki `ask_question` · GitMCP `{prefix}_documentation` + `search_{prefix}_documentation` · **self-hosted OpenDeepWiki** · Mintlify | pre-indexed, no clone, answers "shape" |
| **2** | **Code search (indexed)** | GitMCP `search_{prefix}_code` · `gh search code` · GitHub REST `search/code` | pre-indexed, no clone, returns exact paths + snippets |
| **3** | **Raw code search (last resort)** | `rg` · `git grep` · `ast-grep` · `semgrep` · `ctags` · `git log -S` | local, expensive, runs in a blocking subagent |

Hermes-native `search_files` and `read_file` are **secondary convenience tools**, not a replacement tier: use them for a narrow filename/content lookup or to inspect a small, already-identified file when that is more direct. They do not change the documentation → indexed search → raw search order. Do not use them for broad repo scans, and never as a way around the subagent rule: raw/local shell searches always delegate (§2.1), and `read_file` is for targeted inspection, not bulk reading.

Escalate **only** when the tier above cannot settle the question. "I could have searched
locally" is not a reason to skip tiers 1 and 2.

```
User asks about code / a repo
        │
        ▼
┌──────────────────────────────────────────────┐
│ TIER 1  DOCUMENTATION SEARCH                  │
│   llms.txt/mcpdoc → DeepWiki → GitMCP docs    │
│   answers architecture, usage, intent         │
└──────────────────────────────────────────────┘
        │ insufficient, or needs exact paths?
        ▼
┌──────────────────────────────────────────────┐
│ TIER 2  INDEXED CODE SEARCH (no clone)        │
│   GitMCP search_{prefix}_code → gh search code│
│   returns file paths + snippets               │
└──────────────────────────────────────────────┘
        │ insufficient, or needs exact lines?
        ▼
┌──────────────────────────────────────────────┐
│ TIER 3  RAW CODE SEARCH  (blocking subagent)  │
│   rg → git grep → ast-grep → semgrep → ctags  │
│   → pickaxe; returns ONLY an evidence digest  │
└──────────────────────────────────────────────┘
        │ still insufficient?
        ▼
┌──────────────────────────────────────────────┐
│ TARGETED Hermes read_file of the 1–3 exact   │
│ files earlier tiers named; never bulk reads. │
│ Hermes search_files: narrow convenience only.│
│ Broad/raw search stays in the subagent.      │
└──────────────────────────────────────────────┘
```

**Why docs first:** a doc corpus or DeepWiki answer costs one HTTP call and frequently
settles the question outright. Indexed code search then supplies real `path:line` evidence
without cloning. Only when both are thin — or the question is irreducibly about exact lines
(a specific bug, a precise diff, an unindexed branch) — do you pay for local search.

**Why this does not weaken evidence:** R4 still holds. Tier 1 prose is a hypothesis; tier 2
paths and tier 3 lines are the evidence. Every factual claim still ships `path:line`.

### 2.1 The blocking-subagent contract

Hermes exposes `delegate_task`, a **blocking** subagent call: the main agent dispatches a task and **waits** for the subagent to finish and return its result. It is blocking by design — use that. All raw searching happens inside the subagent; the main agent's context receives only the distilled digest.

Dispatch the subagent whenever **any** of these hold (R6):

- you would make 3 or more search/read calls for one question;
- the combined raw output would exceed ~5000 characters;
- the question needs a scan across many files ("where is X defined?", "which callers...", "does anything use Y?");
- you are comparing more than one repository;
- you need to read a file that is likely longer than ~400 lines.

Those triggers only add to the next rule. **Raw/local shell searches (`rg`, `git grep`, `ast-grep`, and friends) always run in the subagent, however small the query looks** — the 3-call threshold is never a licence to inline one `rg`. A narrow Hermes `search_files` lookup is the only inline exception, and it stops being narrow the moment it becomes raw search or a multi-file investigation.

### 2.2 Evidence digest schema (what the subagent returns)

The subagent must return **only** this structure, under ~1500 words. No file bodies. No tool transcripts.

```yaml
answer:            # 2-6 sentences, direct, no preamble
confidence: high|medium|low
evidence:
  - path: src/agent/skill_manager_tool.py
    lines: "69-81"
    claim: "Skills live under ~/.hermes/skills/ and are seeded from the bundled skills/ catalog."
    quote: "SKILLS_DIR = Path.home() / '.hermes' / 'skills'"   # <= 120 chars, optional
symbols:
  - name: _validate_category
    kind: function|class|method|constant|config
    defined_at: tools/skill_manager_tool.py:133
    called_by: [tools/skills_guard.py:40]
open_questions: []          # anything the search could not settle
commands_run: ["rg -n 'SKILLS_DIR' --glob '*.py'"]
negative_findings: ["no matches for 'skill_cache' in the repo"]  # absences you verified
```

`negative_findings` matter as much as `evidence`: a QA answer that says "nothing does X" is only trustworthy if a search actually ran and returned nothing.

### 2.3 Subagent prompt template (copy verbatim)

```text
You are a code-search retrieval subagent. Work ONLY by searching. Do not summarize from
prior knowledge. Do not read whole files unless a hit requires surrounding context.

Repo: {owner}/{repo}  (local checkout at {path} if present, else clone read-only to /tmp)
Question: {question}

Tools, in order of preference:
  1. rg / git grep  2. ast-grep (sg)  3. gh search code  4. git log -S/-G  5. semgrep/ctags
Rules:
  - Every claim must cite path:line. Anything uncited will be discarded.
  - Prefer --glob filters over grep | head; never scan build/vendor/node_modules.
  - If a search returns >40 hits, narrow it (glob, word boundary, symbol kind) instead of dumping.
  - If you conclude something is ABSENT, record the exact command you ran in negative_findings.
Return ONLY the YAML evidence digest. No preamble, no tool logs, no file contents.
```

For a local checkout, tell the subagent to run the commands itself in `terminal`. For a remote repo, tell it to `git clone --depth 1` (plus `--filter=blob:none` for large monorepos) before searching — never try to "search" a remote repo one HTTP fetch at a time.

---

## 3. Tier 3 — the raw code search toolbelt (last resort)

**Last resort.** Reach for these only after tiers 1 and 2 have failed to settle the question, or when it is irreducibly about exact lines (a specific bug, a precise diff, an unindexed or private branch).
Every entry: **use it when**, **command**, **gotcha**.

### 3.1 `rg` (ripgrep) — first move *within tier 3*

Use when: you have any literal, identifier, string, or error message. Respects `.gitignore`, fast on monorepos.

```bash
# Symbol definition with word boundary + type filter
rg -n --type py '\bclass SkillManager\b'

# Case-insensitive, then read the best 3 hits with context
rg -n -i 'rate.?limit' -g '*.ts' -g '!**/test/**' -C 3

# Multiline: function signature -> first statement
rg -n -U 'def handle_function_call\([^)]*\):\n\s+\S' --type py

# Regex engine power: lookaround, backrefs (needs -P)
rg -n -P '(?<=repoName=)["'"'"'][^"'"'"']+["'"'"']' -g '*.py'

# Only filenames, for a call-graph guess
rg -l 'delegate_task' -g '*.py'
```

**Gotchas:** `rg` skips ignored files — add `-uu` to search `node_modules`, `.env`, or vendored code (then always add `-g` filters or you will drown). `-P` is not available in every build; fall back to `-e` alternation. Never `rg ... | head` without `-m` — use `rg -n -m 20` so the tool itself stops.

### 3.2 `git grep` — tracked files, any revision

Use when: you need to be sure the hit is in version control (no build artefacts), or you need to search a **branch/tag/commit that is not checked out**.

```bash
git grep -n -I 'TODO' main -- 'src/**/*.ts'          # search a ref without switching
git grep -n -e 'foo' -e 'bar' HEAD~5                  # multiple patterns, old revision
git grep -n --function-context 'def load'             # show the whole enclosing function
git grep -l 'apiKey' $(git rev-list --all) -- '*.env*'  # search EVERY commit (slow; cap it)
```

**Gotchas:** `git grep` has no `.gitignore` awareness by default and no PCRE lookbehind unless `-P` is compiled in. Searching all revisions is O(history) — bound it with `git rev-list --max-count=200`.

### 3.3 `ast-grep` (`sg`) — structural / AST queries

Use when: the question is about **code shape** — "every call to X with a string literal first arg", "all `except:` that swallow errors", "all React components missing a key prop". Regex cannot count braces; AST can.

```bash
# Find every call pattern, language inferred from --lang
sg run -p 'logger.error($$$ARGS)' -l python

# Structural rewrite preview (never apply without showing the diff)
sg run -p 'console.log($A)' -l typescript --rewrite 'logger.debug($A)' --dry-run

# List all exported functions in a package
sg run -p 'export function $F($$$) { $$$ }' -l tsx --json | jq '.[].metaVariables.single.F.text'

# Rule file for anything non-trivial
sg scan --rule rules/no-swallowed-exceptions.yml
```

**Gotchas:** `--lang` must match the file grammar or `sg` silently returns nothing — set it explicitly. `sg` is not installed everywhere; if `command -v sg` fails, fall back to `rg -n -U` multiline patterns and say so in `open_questions`.

### 3.4 `semgrep` — lint-grade pattern rules

Use when: you are doing **QA across a repo** (taint, dangerous API use, secrets, framework misuse) rather than a one-off lookup, and you want a rule the team can keep.

```bash
semgrep --config p/security-audit --config p/secrets --json . | jq '.results[] | {path:.path, line:.start.line, msg:.extra.message}'
semgrep --config auto --error --quiet .   # exit 1 on findings; good for CI gates
```

**Gotchas:** first run downloads rules — offline it fails, so treat it as a **second-pass** tool. `--json` output is the only machine-readable form worth parsing.

### 3.5 `ctags` / tree-sitter — definition & call navigation

Use when: you need "where is `X` defined" and `X` is a symbol, not a string, across many languages.

```bash
ctags -R --fields=+n --languages=Python,TypeScript -f - . | grep -P '^\w.*\tkind:func'
# tag file lookup (if .tags / tags exists)
grep -P '^handle_function_call\t' tags
```

**Gotchas:** tags are a snapshot — regenerate after large edits. Prefer `sg` when the query has structure; prefer ctags when it is just a name.

### 3.6 `fd` / `find` — path-level recall

Use when: the question is "is there a file that...", "what test files cover...", "where do the fixtures live".

```bash
fd -e py -t f . src/ | sort
fd -g '*trajectory*' -H --no-ignore
find . -name '*.sql' -not -path '*/node_modules/*' -newermt '2026-01-01'
```

**Gotchas:** `fd` respects `.gitignore` unless `--no-ignore`. Path recall answers "where", never "what" — pair it with `rg` on the filenames you get back.

### 3.7 `git log -S` / `-G` — provenance pickaxe

Use when: "when/why did this change?", "who introduced this bug?", "was this ever different?".

```bash
git log --oneline -S 'repoName' -- '*.py'              # string added or removed (pickaxe)
git log --oneline -G 'repoName\s*=' --since='6 months' # regex that changed
git log -p -L :handle_function_call:tools/model_tools.py   # full history of ONE function
git blame -L 60,90 -- tools/skill_manager_tool.py | sed 's/^\(.\{16\}\).*/\1/'
```

**Gotchas:** `-S` counts occurrences, `-G` matches lines — they give different results; use `-S` for "introduced/removed", `-G` for "edited". `git log -p -L` is the single most underrated QA command: it reconstructs the whole life of a function.

### 3.8 `gh search code` + GitHub code search API

Use when: the repo is **not cloned**, you need cross-repo answers ("who else calls this API?"), or you want to see how a symbol is used in the wild.

```bash
gh search code 'repoName language:python' --limit 20 --json path,repository,textMatches
gh search code 'org:NousResearch "delegate_task"' --limit 20
gh api -X GET search/code -f q='repo:owner/repo filename:config.yaml' --jq '.items[].path'
```

**Gotchas:** requires auth (`gh auth status`), the `search/code` REST endpoint is **30 req/min** and only indexes the default branch; the index lags commits by minutes-to-hours. `textMatches` needs `--json textMatches` explicitly or you get bare paths.

### 3.9 Sourcegraph `src` / public search contexts

Use when: multi-repo or historical (non-default-branch) search matters and you have a Sourcegraph instance or public context.

```bash
src search -display 'context:global lang:python "repoName"' --json
```

**Gotchas:** needs `SRC_ENDPOINT` + token. Without one, do not pretend — fall back to `gh search code`, then to a shallow clone.

### 3.10 Structured dumps — `jq` over JSON/YAML/lockfiles

Use when: the question is about dependencies, configuration, or API surface declared in a data file.

```bash
jq -r '.dependencies | keys[]' package.json
jq -r '.packages | keys[]' pnpm-lock.yaml 2>/dev/null
rg -n 'version' pyproject.toml -A2
```

### 3.11 Availability ladder (what if the tool is missing?)

```
rg missing?      → git grep → grep -rnE
git missing?     → shallow clone impossible → use gh search code / GitMCP code search
sg missing?      → rg -n -U multiline patterns; note the degradation in open_questions
gh not authed?   → GitMCP search_{prefix}_code → DeepWiki ask_question
no network?      → local tools only; say so explicitly in the answer's confidence field
```

**Always state degradations.** "I could not run `ast-grep`, so structural matches were approximated with multiline regex" is a good sentence. Silence is not.

### 3.12 CI state evidence — `gh api …/actions/jobs/<id>/logs`

Use when: a claim depends on "CI is green / the job passed / the refresh ran" — run conclusions
and step conclusions both lie about *effect*.

```bash
gh run list --repo O/R --workflow <file> --limit 6 --json databaseId,conclusion,createdAt
gh api "repos/O/R/actions/runs/<id>/jobs" --jq '.jobs[]|"\(.name) \(.conclusion)", (.steps[]|"  \(.number) \(.name): \(.conclusion)")'
jid=$(gh api "repos/O/R/actions/runs/<id>/jobs" --jq '.jobs[0].id')
gh api "repos/O/R/actions/jobs/$jid/logs" > /tmp/ci.log   # then grep '##[error]|Warning|Skipped'
```

**Gotchas:** `gh run view <id> --log-failed` often prints an empty body even for failed runs — go
straight to the jobs-logs endpoint. A step reported `success` can still have done nothing (the
`if [ -z "$(git status --porcelain …)" ]` early-exit pattern), and a later step failing after a
`git push` leaves real state on a branch with no PR. Cite the log line, not the colour.

---

## 4. Tier 1 — documentation retrieval (via `mcporter`, `npx`)

Use this layer for **shape and intent**: architecture, "how do I use X", migration notes, design rationale. It is AI-synthesized prose — never let it be the *only* source for a factual code claim (R5).

### 4.1 MCP servers

| Server | Source | Auth | Best For |
|--------|--------|------|----------|
| DeepWiki | `https://mcp.deepwiki.com/mcp` | None | Architecture docs, how-to questions |
| GitMCP | `https://gitmcp.io/{owner}/{repo}` | None | Per-repo docs, code search, examples |
| **OpenDeepWiki (self-hosted)** | `http://<your-host>:8080/api/mcp` | None behind a private network | Private/internal repos, your own index — see §4.8 |
| Mintlify | `https://{subdomain}.mintlify.app/mcp` | None for public docs | Mintlify-hosted docs |
| GitHub MCP | `https://api.githubcopilot.com/mcp/` | GitHub PAT | File contents, issues, PRs |

### 4.2 mcporter basics

```bash
npx mcporter --version
npx mcporter list --http-url "https://gitmcp.io/owner/repo"
```

### 4.3 DeepWiki query

```bash
# ⚠️ Parameter is repoName (camelCase), NOT repo_name (snake_case)
npx mcporter call --http-url "https://mcp.deepwiki.com/mcp" \
  ask_question \
  repoName="NousResearch/hermes-agent" \
  question="How does the skill system work?" \
  --output json
```

**⚠️ Parameter gotcha:** `ask_question` uses `repoName` (camelCase). `repo_name` fails with "Missing required argument [repoName]". DeepWiki also has `read_wiki_structure(repoName)` and `read_wiki_contents(repoName)`.

### 4.4 GitMCP ad-hoc mode (recommended)

```bash
npx mcporter call \
  --http-url "https://gitmcp.io/NousResearch/hermes-agent" \
  search_hermes_agent_code \
  query="sharegpt OR trajectory" \
  --output json
```

**Tool name pattern:** `{server_prefix}.{tool}` — e.g. `fetch_hermes_agent_documentation`, `search_hermes_agent_code`, `fetch_generic_url_content`. **Discover the prefix first** with `npx mcporter list --http-url ...`.

### 4.5 Fetch raw documentation files

```bash
npx mcporter call \
  --http-url "https://gitmcp.io/NousResearch/hermes-agent" \
  fetch_generic_url_content \
  url="https://raw.githubusercontent.com/owner/repo/main/docs/file.md" \
  --output json
```

### 4.6 GitMCP tool reference

| Tool | Purpose |
|------|---------|
| `{prefix}_documentation()` | Fetch llms.txt / generated docs |
| `search_{prefix}_documentation(query)` | Semantic search in docs |
| `search_{prefix}_code(query, page?)` | GitHub code search |
| `fetch_generic_url_content(url)` | Fetch any raw URL |

### 4.7 Aggregated query pattern with fallback

```bash
#!/bin/bash
REPO="NousResearch/hermes-agent"
QUERY="How does trajectory export work?"

npx mcporter call --http-url "https://mcp.deepwiki.com/mcp" \
  ask_question repoName="$REPO" question="$QUERY" --output json \
  > /tmp/result.json 2>/dev/null \
  || { echo "DeepWiki unavailable, using GitMCP..."; \
       PREFIX=$(echo "$REPO" | tr '/' '_'); \
       npx mcporter call --http-url "https://gitmcp.io/$REPO" \
         "search_${PREFIX}_code" query="trajectory export" --output json \
         > /tmp/result.json; }
```

### 4.8 Mintlify API keys

No API key required for public Mintlify documentation sites — just use `https://{your-subdomain}.mintlify.app/mcp`. Private/restricted docs may require authentication via dashboard settings.

### 4.9 llms.txt corpora and mcpdoc browsing

For a known site, probe its fixed `llms.txt` paths. For an unknown host, use `references/llms-txt-discovery.md`, including its path-based lookup for `afterpartyai/llms_txt_store`. Those generated summaries are discovery leads, not publisher-maintained documentation; verify important claims against current first-party sources. Validate any candidate before trusting it; generic search-operator behavior stays in `searxng-search`.

Once you have a real corpus URL, `mcpdoc` exposes it as an MCP documentation server. Prerequisites: `uvx` for mcpdoc and `npx` for mcporter. Bind locally; do not register a persistent gateway server just to browse a corpus. The source list is a candidate, not authority: some commonly cited paths are stale or return HTML, so validate each URL first.

**SDK compatibility:** current `mcpdoc` code imports the MCP SDK v1 `FastMCP` API. If an unpinned `uvx --from mcpdoc` install resolves SDK v2 and fails with `No module named 'mcp.server.fastmcp'`, add `--with 'mcp<2'` to the uvx command.

Useful candidates to check:

- LangChain: `langchain-ai.github.io/langgraph/llms.txt`, `python.langchain.com/llms.txt`, `langchain-ai.github.io/langgraphjs/llms.txt`, `js.langchain.com/llms.txt`
- Frameworks: `react.dev/llms.txt`, `nextjs.org/llms.txt`, `vuejs.org/llms.txt`
- Infrastructure/data: `docs.docker.com/llms.txt`, `git-scm.com/llms.txt`, `postgresql.org/docs/llms.txt`, `techdocs.akamai.com/llms.txt`

Use `--urls` with one or more `Name:URL` sources. The server defaults to stdio; for an ad-hoc `mcporter` HTTP session, choose SSE and bind only to localhost:

| Option | Default | Purpose |
|---|---|---|
| `--urls` | required | One or more `Name:URL` corpus sources |
| `--transport` | `stdio` | Choose `sse` for HTTP access |
| `--host` | `127.0.0.1` | SSE bind address |
| `--port` | `8000` | SSE port |
| `--allowed-domains` | — | Additional link hosts; the source hosts remain allowed; `'*'` disables the allowlist |
| `--follow-redirects` | off | Follow source redirects |
| `--timeout` | `10.0` | Per-request timeout in seconds |
| `--yaml` / `--json` | — | Load sources from a config file |

A persistent Hermes MCP registration is optional; it needs configuration changes and a gateway restart, which are the operator's call. Prefer the temporary local SSE path for ordinary browsing.

With current mcporter, local plain-HTTP endpoints require the explicit `--allow-http` acknowledgement; include it on each `list` or `call` command below.

```yaml
mcp:
  servers:
    mcpdoc-docs:
      transport: sse
      url: http://127.0.0.1:8082/sse
```

```bash
uvx --from mcpdoc --with 'mcp<2' mcpdoc \
  --urls "Docs:https://docs.example.com/llms.txt" \
  --follow-redirects --transport sse --host 127.0.0.1 --port 8082
```

For a short, one-shot query, run the server in the foreground in one terminal and call it from another. For work spanning turns, redirect its output and run it in the background; stop the process when finished.

```bash
npx mcporter list --allow-http --http-url "http://127.0.0.1:8082/sse"
npx mcporter call --allow-http --http-url "http://127.0.0.1:8082/sse" list_doc_sources --output json
npx mcporter call --allow-http --http-url "http://127.0.0.1:8082/sse" fetch_docs \
  url="https://docs.example.com/llms.txt" --output json
```

The two tools are `list_doc_sources()` and `fetch_docs(url)`: list sources, choose a URL from the corpus, then fetch that page. `fetch_docs` only returns URLs allowed by its source-domain policy. Add only expected link domains; `--allowed-domains '*'` disables that restriction and should be used only when unrestricted fetching is intentional. Useful options are `--follow-redirects` for redirecting hosts, `--timeout 30` for slow sources, and `--yaml` / `--json` for a source config:

```yaml
sources:
  - name: Docs
    llms_txt: https://docs.example.com/llms.txt
    description: Product documentation
```

```bash
uvx --from mcpdoc --with 'mcp<2' mcpdoc --yaml ./mcpdoc-sources.yaml \
  --transport sse --host 127.0.0.1 --port 8082
```

The JSON equivalent uses `{"sources": [{"name": "Docs", "llms_txt": "https://docs.example.com/llms.txt"}]}`. Use the same `list_doc_sources()` / `fetch_docs(url)` flow above; `fetch_docs` restricts retrieval to allowed domains.

Troubleshooting:

| Symptom | Check |
|---|---|
| `Domain not allowed` | Add only the linked host(s) you expect; use `--allowed-domains '*'` only if unrestricted fetching is intentional. |
| Connection refused | Confirm the process is running and host/port/transport match the URL used by mcporter. |
| Empty results | Revalidate the corpus; it may be an HTML shell, malformed, or stale. |
| Slow source | Raise `--timeout` (for example, `--timeout 30`). |
| Redirect loop or empty body | Enable `--follow-redirects`, then validate the final URL and body. |

Browsing a repository's own documentation is usually simpler through DeepWiki or GitMCP; use mcpdoc when you want an external documentation corpus addressable as an MCP server. A persistent Hermes MCP registration is optional and requires a gateway restart; prefer this temporary local SSE path unless persistent access is specifically needed.

### 4.10 Configuration (optional)

```bash
npx mcporter config add deepwiki --url "https://mcp.deepwiki.com/mcp"
npx mcporter config add github \
  --url "https://api.githubcopilot.com/mcp/" \
  --header "Authorization: Bearer $GITHUB_PAT"
```

### 4.11 Self-hosted OpenDeepWiki — the OSS DeepWiki/GitMCP equivalent

DeepWiki and GitMCP are SaaS: they only see **public** repos, and every question you ask leaves
your network. When the repo is private, internal, or you would rather not narrate your
architecture to a third party, run the same tier yourself.
[OpenDeepWiki](https://github.com/AIDotNet/OpenDeepWiki) is an open-source wiki generator
(ASP.NET backend + Next.js UI + SQLite, MIT) that indexes a repository, produces a structured
wiki with an LLM of your choice, and exposes it over MCP. It is the self-hosted stand-in for both
`mcp.deepwiki.com` and `gitmcp.io`:

| Capability | DeepWiki / GitMCP | Self-hosted OpenDeepWiki |
|---|---|---|
| Public repo docs | yes | yes |
| **Private / internal repo docs** | no | **yes** (needs clone credentials, below) |
| Question leaves your network | yes | no |
| Index you control / can re-generate | no | yes |
| Cost | free (rate-limited) | your own inference endpoint |

**Deploy** (any Docker host; ~2 GB RAM is enough for small repos):

```yaml
# docker-compose.yml — backend publishes on a private interface only
services:
  odw-backend:
    image: <registry>/opendeepwiki:latest
    container_name: odw-backend
    ports: ["<private-ip>:8080:8080"]
    env_file: [odw.env]
  odw-web:
    image: <registry>/opendeepwiki-web:latest
    container_name: odw-web
    ports: ["127.0.0.1:8090:3000"]
    depends_on: [odw-backend]
```

`odw.env` keys that matter for QA work — note the **double-underscore** convention, `ENDPOINT`
is an OpenAI-compatible base URL:

```bash
# inference
ENDPOINT=https://<your-openai-compatible-gateway>/v1
CHAT_API_KEY=<key>
CHAT_MODEL=<model-id>
# expose the MCP server
MCP_ENABLED=true
# generation knobs (double underscore = config section)
WikiGenerator__DocumentGenerationTimeoutMinutes=120
WikiGenerator__ParallelCount=2
```

**Tools it exposes** (`/api/mcp`, 7 of them):

| Tool | Purpose |
|---|---|
| `list_repositories` | what is indexed, with branch/language |
| `search_repositories` | route a question to the right repo |
| `search_docs` | search the generated wiki — **pass `language: "en"`**; the default is `zh` and returns silent zero hits on an English index |
| `read_doc` | full text of one wiki document |
| `get_repo_structure` | directory tree of the indexed repo |
| `search_doc` | search within one repository's docs |
| `read_file` | read a source file from the indexed repo |

**Query it with mcporter** (same shape as the SaaS servers):

```bash
# discover first — the prefix comes from the server, not from you
npx mcporter list --http-url "http://<your-host>:8080/api/mcp"

npx mcporter call --http-url "http://<your-host>:8080/api/mcp" \
  search_docs query="hook registration" owner="owner" repo="repo" language="en" --output json
```

**Or register it as a native MCP server** so your agent gets the tools directly instead of
shelling out (Hermes example — the server name becomes the tool prefix):

```bash
hermes config set mcp_servers.opendeepwiki.url "http://<your-host>:8080/api/mcp"
hermes mcp test opendeepwiki     # expect "Connected" + "Tools discovered: 7"
# → mcp_opendeepwiki_search_docs, mcp_opendeepwiki_read_doc, mcp_opendeepwiki_list_repositories, …
```

**Private repos — the sharp edge.** Importing a GitHub repo through the app's own UI/API works for
public repos immediately. A private clone needs credentials on the *repository row*: the clone
path uses username/password credentials only, so an API token that browses repos is not enough.
Two working shapes:

- a fine-grained PAT with `Contents: Read-only` on just those repos, stored as the repo's
  `authAccount`/`authPassword`; or
- a GitHub App installation token (`x-access-token` as the username), which expires after
  **1 hour** and must be re-minted and re-written to the row before a regenerate — a cron job or
  a pre-flight script, not a one-off.

Either way the credential ends up in the SQLite DB and in every backup of it: scope the token
tightly and treat that file as a secret. Also note that whatever the MCP endpoint can read, the
agent talking to it can read — publish the port on a private network (VPN/tailnet), never the
internet.

---

## 5. Decision tree

```
Need to understand code?
│
├─ TIER 1 — documentation search (always start here)
│   llms.txt corpus / mcpdoc → DeepWiki ask_question → GitMCP {prefix}_documentation
│   └─ answers "how does X work" / "what is this project"?
│        └─ verify the 1–3 load-bearing claims at tier 2 → answer with path:line
│
├─ TIER 2 — indexed code search (no clone)
│   GitMCP search_{prefix}_code → gh search code
│   └─ returns exact paths + snippets? → cite path:line → answer
│
├─ TIER 3 — raw local code search (LAST RESORT, blocking subagent §2)
│   rg → git grep → ast-grep → semgrep → ctags → git log -S
│   └─ digest back → cite path:line → answer
│
└─ Still unresolved?
    ├─ TARGETED Hermes read_file of the exact files earlier tiers named
    │  (max 3 files, max ~400 lines each) — no bulk reads
    └─ Hermes search_files only for a narrow filename/content lookup;
       broad or raw repository searches stay in the blocking subagent
```

## 6. When to use this skill

✅ **USE FIRST** for: project structure & architecture · learning a library's API · finding examples & usage patterns · recent changes or deprecations · **any "where is X / who calls Y / what does Z do" question** · pre-QA context before editing · finding or browsing `llms.txt` documentation corpora.

❌ **DO NOT USE** for: questions about code you are already holding in context · non-code questions · repos you cannot access at all (say so instead of guessing).

---

## 7. Error handling

| Error | Meaning | Fallback |
|-------|---------|----------|
| `gh repo qa: command not found` / shim banner | You tried the invented command | Do not retry. Read §3 and dispatch a subagent. |
| DeepWiki query unavailable | Endpoint failed or returned no useful result | Use GitMCP or targeted source search |
| "Tool not found" | Wrong MCP tool name | `npx mcporter list --http-url ...` |
| "Repo not found" | Private repo | GitHub MCP with PAT, or `gh search code` |
| "Empty results" | Query too specific | Broaden, then narrow with `--glob` |
| `rg: no matches` | Real absence | Record it in `negative_findings`; do not invent a hit |
| `command not found: sg` | ast-grep absent | §3.11 degradation ladder |
| "Connection failed" | Network/MCP issue | Local search layer needs no network — prefer it |
| Subagent returns >1500 words | Digest failed the contract | Re-dispatch with a narrower question, not a bigger read |

---

## 8. Integration with Hermes

- **Search dispatch:** `delegate_task` — **blocking**. The main agent waits for the subagent and receives only the evidence digest. This is the default home for §3.
- **Command execution:** `execute_code` / `terminal` for `rg`, `git`, `npx mcporter`, `gh`.
- **Targeted reads:** Hermes `read_file`, at most 3 files per question, only for paths earlier retrieval named. During raw investigation, the subagent uses shell tools for surrounding context.
- **Secondary native lookup:** Hermes `search_files` may help with a narrow filename/content lookup. Keep it bounded and subordinate to tiers 1–2; do not use it for broad repository scans. If it expands into raw/local search or multi-file investigation, use a blocking subagent as §2.1 requires.
- **Web fallback:** `web_extract` on raw GitHub URLs, or `browser_navigate` on GitHub browse pages.

Rule of thumb (R6): **3+ retrieval calls for one question, or >5000 chars of raw output → delegate to a blocking subagent.** Under that, do it inline and keep moving — except raw/local shell searches, which always delegate (§2.1).

### Key insight from practice

DeepWiki is useful for AI-synthesized answers; GitMCP is effective for targeted searches and raw file fetches. Keep the other available as a fallback. Always use `--http-url` with mcporter for zero-config queries. **Critical gotcha:** DeepWiki uses `repoName` (camelCase), not `repo_name`.

---

## 9. Anti-patterns (stop doing these)

1. **Answering "where is X defined?" from training data.** Follow the ordered tiers; once tiers 1–2 come up short, a narrow `search_files` *filename* lookup may help. Any content search is a blocking-subagent step, not an opening move.
2. **Dumping `rg` output into your own context and reasoning over 400 hits.** Re-dispatch with `--glob` and `-m`.
3. **`grep -rn .` over the repo root.** It walks `node_modules`, `.git`, and build output. Always scope.
4. **Citing a file you never opened.** A path from a doc summary is a lead, not evidence.
5. **Calling `gh repo qa`.** See §1. There is a shim, and it will stop you.
6. **Opening with local `rg`/`grep` on a repo question.** That is tier 3. Start with a doc corpus or DeepWiki, then indexed code search, and only then search locally.
7. **Reading whole files to answer one line's question.** `rg -n -C 5` is the tool.
8. **Presenting synthesized prose as a quote from the code.** Prose from DeepWiki is a hypothesis; `path:line` is the fact.

---

## 10. Worked examples

### 10.1 "How does X work?" — shape question, then verification

```bash
# Layer 2: synthesized overview
npx mcporter call --http-url "https://mcp.deepwiki.com/mcp" \
  ask_question repoName="NousResearch/hermes-agent" \
  question="How does the skill system load and validate SKILL.md?" --output json \
  | jq -r '.content[].text' | head -120

# Layer 1 verification of the load-bearing claim (or delegate both together)
rg -n 'parse_frontmatter|MAX_SKILL_CONTENT_CHARS' -g '*.py' -C 2
```

### 10.2 "Where is `handle_function_call` defined and who calls it?" — delegate

Dispatch the §2.3 template with `Question: where is handle_function_call defined, and which modules call it?`
Expect back: `defined_at: tools/model_tools.py:NNN`, `called_by: [...]`, plus `commands_run`.
Cost to your context: one YAML block. Cost if done inline: 5 searches and two file reads.

### 10.3 "Did the `repoName` parameter rename break callers?" — provenance

```bash
git log --oneline -S 'repo_name' -- '*.py'
git log --oneline -S 'repoName' -- '*.py'
git grep -n 'repo_name' $(git rev-list --max-count=200 HEAD) -- '*.py' | head -20
```

### 10.4 Comparing multiple repositories (always delegate)

```bash
for REPO in "langchain-ai/langchain" "run-llama/llama_index"; do
  PREFIX=$(echo "$REPO" | tr '/' '_')
  npx mcporter call --http-url "https://gitmcp.io/$REPO" \
    "search_${PREFIX}_code" query="RAG implementation" --output json \
    > "/tmp/${PREFIX}_rag.json" &
done
wait
```

---

## 11. `gh` shim install (optional)

```bash
SKILL_DIR=/path/to/github-qa-retrieval
mkdir -p "$HOME/.local/bin"
ln -sfn "$SKILL_DIR/scripts/gh-shim.sh" "$HOME/.local/bin/gh"
```

The shim resolves `SKILL.md` relative to its own symlink-resolved location, so it works across skill directories and platforms with Bash. Its log defaults to `${HERMES_HOME:-$HOME/.hermes}/logs/gh-qa-shim.log`; set `HERMES_HOME` to change the base. Set `GH_SHIM_REAL_GH` if the real binary is not `/usr/bin/gh`.

---

**Remember:** documentation search first, indexed code search second, raw local search last. Cite `path:line` or don't answer.
