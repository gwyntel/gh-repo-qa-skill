#!/usr/bin/env bash
# gh shim — intercepts the non-existent `gh repo qa` subcommand and forces a
# read of the github-qa-retrieval skill. Everything else passes through to the
# real gh binary (default /usr/bin/gh).
#
# WHY THIS EXISTS
#   `gh repo qa --help` does NOT error. gh parses `repo` as the subcommand and
#   `qa`/`--help` as trailing flags/args, so it prints ordinary `gh repo` help
#   with exit code 0. Smaller models take that as proof the command works and
#   then invent arguments for it instead of loading the github-qa-retrieval
#   skill (which does repo QA via DeepWiki/GitMCP over mcporter). This shim
#   turns the silent false-success into a hard failure + the full skill text,
#   so the model gets corrected mid-run and still completes the user's task.
#
# INSTALL (idempotent; set SKILL_DIR to this installed skill directory):
#     mkdir -p "$HOME/.local/bin"
#     ln -sfn "$SKILL_DIR/scripts/gh-shim.sh" "$HOME/.local/bin/gh"
#
# Intercepts: gh repo qa <anything...>; unrelated repo commands pass through
# Logs each interception to ${HERMES_HOME:-$HOME/.hermes}/logs/gh-qa-shim.log

set -u

REAL_GH="${GH_SHIM_REAL_GH:-/usr/bin/gh}"

# Locate SKILL.md from this script's own resolved path, so the shim works from
# any install layout and not only from $HERMES_HOME. Symlink-safe; needs Bash.
_self="${BASH_SOURCE[0]}"
case "$_self" in /*) ;; *) _self="$PWD/$_self" ;; esac
while [ -L "$_self" ]; do
    _link="$(readlink "$_self")"
    case "$_link" in
        /*) _self="$_link" ;;
        *)  _self="${_self%/*}/$_link" ;;
    esac
done
SKILL="$(cd "${_self%/*}/.." && pwd)/SKILL.md"
[ -r "$SKILL" ] || SKILL="${HERMES_HOME:-$HOME/.hermes}/skills/github-qa-retrieval/SKILL.md"

LOG_DIR="${HERMES_HOME:-$HOME/.hermes}/logs"
LOG="$LOG_DIR/gh-qa-shim.log"

if [ "$#" -ge 2 ] && [ "$1" = "repo" ] && [ "$2" = "qa" ]; then
    mkdir -p "$LOG_DIR" 2>/dev/null
    printf '%s  cwd=%s  args=%s\n' \
        "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$PWD" "$(printf '%q ' "$@")" >>"$LOG" 2>/dev/null

    cat >&2 <<'BANNER'
================================================================================
  ✗  `gh repo qa` DOES NOT EXIST. You just invented a command.
================================================================================

It did not error before this shim was installed — gh fell through to
`gh repo --help` and exited 0, which is why it looked like it worked.
Do NOT retry it with different arguments; no argument spelling makes it real.

There is no `gh repo qa`. Repo QA / documentation retrieval is done by the
github-qa-retrieval skill, which drives free MCP servers (DeepWiki, GitMCP)
through `mcporter` (via npx). The full skill text follows — read it, then do
the task the user actually asked for using the commands it specifies.

  Skill:    github-qa-retrieval
  Path:     resolved relative to this shim
  Load it:  skill_view(name='github-qa-retrieval')
  Rapid form:
      npx mcporter call --http-url "https://mcp.deepwiki.com/mcp" \
        ask_question repoName="owner/repo" question="..." --output json
      npx mcporter call --http-url "https://gitmcp.io/owner/repo" \
        fetch_owner_repo_documentation --output json

  (DeepWiki arg is repoName, camelCase — repo_name fails.)

--------------------------------------------------------------------------------
BANNER

    if [ -r "$SKILL" ]; then
        cat "$SKILL" >&2
    else
        echo "!! Skill file not readable at $SKILL — load via skill_view instead." >&2
    fi

    cat >&2 <<'FOOTER'
--------------------------------------------------------------------------------

  ↑ That is the whole skill. Now execute the user's original request with
    mcporter + DeepWiki/GitMCP. Do not call `gh repo qa` again.

================================================================================
FOOTER

    exit 1
fi

exec "$REAL_GH" "$@"
