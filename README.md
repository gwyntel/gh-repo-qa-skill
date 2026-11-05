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
├── SKILL.md              # the skill: metadata + full workflow
└── scripts/
    └── gh-shim.sh        # optional `gh` interceptor for `gh repo qa`
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
