# GitHub QA Retrieval — an Agent Skill

Repository understanding and documentation retrieval for coding agents, without
reading source files one at a time.

The skill drives two free MCP documentation servers through
[`mcporter`](https://www.npmjs.com/package/mcporter) (`npx`, no global install):

- **DeepWiki** — `https://mcp.deepwiki.com/mcp` — AI-synthesized answers to
  "how does this work?" questions about a repository.
- **GitMCP** — `https://gitmcp.io/<owner>/<repo>` — per-repo docs, code search,
  and raw file fetches.

You get architecture, API usage, and examples in one call, and fall back to
manual file reading only when the QA layer is genuinely insufficient.

It also covers **documentation corpora**: how to find a site's `llms.txt` /
`llms-full.txt` without crawling it, and how to serve one you found as an MCP
doc server with `mcpdoc`.

It also ships an optional `gh` shim that turns a very specific silent failure
into a loud one — see [Why this exists](#why-this-exists).

## Why this exists

**`gh repo qa` is not a real command.** There is no such subcommand in the
GitHub CLI, and there never was.

It is dangerous precisely because it *does not error*: `gh` parses `repo` as the
subcommand and treats `qa` as a trailing argument, falls through to
`gh repo --help`, prints ordinary repository help, and **exits 0**. An agent
reads that exit code as success and starts inventing arguments for a command
that does not exist, instead of loading this skill and doing the retrieval the
user actually asked for.

The task that imaginary command pretends to perform is the task this skill
performs. Hence the shim: `scripts/gh-shim.sh` intercepts `gh repo qa …`
(and `gh repo qar …` and friends), prints a correction banner plus the full
`SKILL.md` to stderr, and exits `1`. Every other invocation execs straight
through to the real `gh` binary unchanged.

## Layout

```
skills/github-qa-retrieval/
├── SKILL.md                          # the skill: metadata + full workflow
├── references/
│   ├── llms-txt-discovery.md         # find a doc corpus: probe, dork, sweep, validate
│   └── mcpdoc-browsing.md            # serve a found corpus as an MCP doc server
└── scripts/
    └── gh-shim.sh                    # optional `gh` interceptor for `gh repo qa`
```

`SKILL.md` frontmatter `name` matches its directory name, as the
[Agent Skills](https://agentskills.io) spec requires.

## Install

Using the Vercel `skills` CLI (installs into whatever agent target you pick —
Claude Code, Codex, Cursor, OpenCode and others):

```bash
npx skills add gwyntel/gh-repo-qa-skill --skill github-qa-retrieval
```

Direct path to the skill inside the repository:

```bash
npx skills add https://github.com/gwyntel/gh-repo-qa-skill/tree/main/skills/github-qa-retrieval
```

The Vercel CLI installs the skill and its support files into your selected
agent's skills folder. If you prefer a manual install, clone the repository and
copy the complete directory. For example, in Hermes:

```bash
git clone https://github.com/gwyntel/gh-repo-qa-skill.git
mkdir -p "$HOME/.hermes/skills"
cp -R gh-repo-qa-skill/skills/github-qa-retrieval "$HOME/.hermes/skills/"
```

For Claude Code, the corresponding target is `~/.claude/skills/`; other agents
may use a different skills directory. Prerequisites: Node.js with `npx` (for
`mcporter`) and Git (for the full clone). No API keys — DeepWiki and GitMCP are
free and keyless for public repositories.

## Install the `gh` shim (optional)

The shim is a small bash script. Set `SKILL_DIR` to the directory containing
the installed skill, then link the shim somewhere earlier on `PATH` than the
real `gh`:

```bash
SKILL_DIR=/path/to/github-qa-retrieval
mkdir -p "$HOME/.local/bin"
ln -sfn "$SKILL_DIR/scripts/gh-shim.sh" "$HOME/.local/bin/gh"
```

`~/.local/bin` is a good target because it precedes `/usr/bin` on most distros
and is inherited by non-interactive/service shells (unlike `~/bin` on some
setups). Verify both behaviours:

```bash
gh repo qa owner/repo   # must exit 1 and print the skill
gh --version            # must pass straight through
```

Interceptions are logged to `${HERMES_HOME:-$HOME/.hermes}/logs/gh-qa-shim.log`
with timestamp, working directory, and arguments — useful for finding out which
agents keep making the mistake.

The shim resolves `SKILL.md` relative to its own symlink-resolved location, so it
works from any install layout, not just a fixed prefix. The default real binary
is `/usr/bin/gh`; on macOS or another layout, set `GH_SHIM_REAL_GH` to the real
binary path before invoking the shim.

To remove it, delete the symlink: `rm "$HOME/.local/bin/gh"`.

## Usage

Ask the agent about a repository and it uses the workflow in `SKILL.md`:

```bash
# AI-synthesized answer about a repo (note: repoName is camelCase)
npx mcporter call --http-url "https://mcp.deepwiki.com/mcp" \
  ask_question repoName="owner/repo" question="How does the plugin system work?" \
  --output json

# Per-repo documentation
npx mcporter call --http-url "https://gitmcp.io/owner/repo" \
  fetch_owner_repo_documentation --output json

# Code search inside that repo
npx mcporter call --http-url "https://gitmcp.io/owner/repo" \
  search_owner_repo_code query="retry with backoff" --output json
```

Tool prefixes are derived from the repository path (`NousResearch/hermes-agent`
becomes `hermes_agent`), so run `npx mcporter list --http-url …` once to discover
the exact names.

Good fits: architecture questions, library usage, finding examples, pre-reading
context. Bad fits: line-precise bug hunting, uncommitted changes, private repos
without a PAT.

## Documentation corpora (`llms.txt`)

Many doc sites publish their whole documentation as one Markdown file. Fetching
that beats crawling: `llms.txt` is a curated index, `llms-full.txt` inlines every
page. The skill treats these as a first-class retrieval path.

**Find one** — probe the fixed paths before searching, because the path is
already known:

```bash
for p in llms.txt llms-full.txt .well-known/llms.txt .well-known/llms-full.txt; do
  printf '%s/%s  ' "$SITE" "$p"
  curl -sL -A 'Mozilla/5.0' -o /dev/null -w '%{http_code} %{size_download} %{url_effective}\n' "$SITE/$p"
done
```

If the host is unknown, the fallbacks in `references/llms-txt-discovery.md` are a
`filetype:txt llms-full` dork through a local SearXNG, a GitHub filename sweep
(`gh api "search/code?q=filename:llms-full.txt"`), and the public registries.

**Validate before trusting.** HTTP 200 proves nothing here: SPA routes echo the
path back as HTML, some servers 301 `llms-full.txt` to `llms.txt`, and at least
one CDN serves a 401-byte `# Page Not Found` with status 200. Check
`Content-Type`, the first line of the body, the final URL after redirects, and
that `llms-full.txt` is not byte-identical to `llms.txt`.

**Serve it** — once you have a real corpus URL, `mcpdoc` exposes it over MCP:

```bash
uvx --from mcpdoc mcpdoc --urls "Mine:https://docs.example.com/llms.txt" \
  --transport sse --port 8082 &
npx mcporter call --http-url "http://localhost:8082/sse" list_doc_sources --output json
npx mcporter call --http-url "http://localhost:8082/sse" fetch_docs url="…" --output json
```

## Updating

With the Vercel CLI:

```bash
npx skills update github-qa-retrieval
```

With a git clone, pull and re-copy:

```bash
cd gh-repo-qa-skill && git pull --ff-only
cp -R skills/github-qa-retrieval ~/.claude/skills/
```

## Troubleshooting

- **`gh repo qa` seems to work and prints help.** That is the failure this skill
  documents, not a working command. If the shim is installed you get exit `1`
  instead.
- **`Missing required argument [repoName]`.** DeepWiki's parameter is camelCase
  `repoName`; `repo_name` fails.
- **`Tool not found`.** Discover the real tool names with
  `npx mcporter list --http-url "https://gitmcp.io/owner/repo"`.
- **Empty or rate-limited results.** DeepWiki limits aggressively under load;
  the skill falls back to GitMCP code search and raw fetches.
- **Private repository returns nothing.** DeepWiki/GitMCP index public
  repositories; use the GitHub MCP server with a PAT instead.
- **Skill not discovered by the agent.** Check the frontmatter opens with `---`
  at byte 0, `name` equals the directory name, and the description leads with a
  trigger phrase.

## Compatibility

Plain Markdown plus POSIX shell and Node — no agent-specific code in `SKILL.md`.
The shim is the only host-assuming part: by default it logs under
`${HERMES_HOME:-$HOME/.hermes}`, and setting `HERMES_HOME` or `GH_SHIM_REAL_GH`
adapts it to other layouts.

## License

MIT — see [LICENSE](LICENSE). The skill is authored by Hermes Agent and
maintained here by GwynTel. The original MIT license and upstream copyright
attribution are preserved.
