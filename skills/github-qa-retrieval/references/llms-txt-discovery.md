# llms.txt / llms-full.txt Discovery

Find machine-readable documentation corpora for a domain, org, or topic. This file is
discovery only — once you have a corpus and want to *browse* it as an MCP doc server, see
`references/mcpdoc-browsing.md`. Generic search-operator syntax (how `site:`, `filetype:`,
`inurl:` behave per engine) lives in the `searxng-search` skill; this file only records how
to aim those operators at llms.txt.

## What the files are

- `/llms.txt` — curated index. H1 site name, blockquote summary, H2 sections of
  `- [title](url): description`. Usually a few KB to ~100 KB.
- `/llms-full.txt` — every page of the docs inlined as Markdown. Hundreds of KB to tens of MB.
- `/.well-known/llms.txt` and `/.well-known/llms-full.txt` — Mintlify's compatibility mirrors.
  Verified byte-identical to the root files (docs.x.com, mintlify.com/docs).
- Mintlify splits an index over 100,000 characters into `/_llms/<section>.txt` files that link to
  further `/_llms/*.txt` files. Follow them recursively; the split never drops pages.

Both are conventions, not a protocol. Most sites do not publish them, and a URL that answers
200 does not mean the content is real (see the validation gate).

## Order of attack

Probe → dork → GitHub filename sweep → registries. Never start with a web search for a
*known* domain: the path is fixed, so request it. Search is for when you do not know the host.

## 1. Probe the fixed paths (default first move)

```bash
for p in llms.txt llms-full.txt .well-known/llms.txt .well-known/llms-full.txt; do
  echo -n "$1/$p  "
  curl -sL -A 'Mozilla/5.0' -o /dev/null -w '%{http_code} %{size_download} %{url_effective}\n' "$1/$p"
done
```

`-L` plus `%{url_effective}` is mandatory: redirects are the main source of false positives.

Measured 2026-11-04 (bytes actually downloaded, `curl -sL`):

| Host | `/llms.txt` | `/llms-full.txt` |
|---|---|---|
| docs.anthropic.com | 97,836 | 50,301,897 |
| docs.stripe.com | 97,537 | 404 |
| developers.openai.com | 6,201 | 9,730,858 |
| docs.github.com | 28,642 | 404 |
| docs.x.com | 3,467 | 4,794,924 |
| mintlify.com/docs | 25,275 | 1,752,300 |
| docs.aws.amazon.com | 411,047 | 815,134 |
| docs.nvidia.com/dynamo | 1,714 | **fake** — 301 to `/dynamo/llms.txt` |
| llmstxt.org | 200 (index only) | 404 |

For a whole domain list, run the probe 8–18 ways in parallel; it costs one request per path per
host and needs no key.

## 2. Dork, when the host is unknown

SearXNG is the only local engine that will honour `filetype:`, and only through `startpage`:

```bash
curl -s "http://localhost:8080/search?q=filetype%3Atxt+llms-full&format=json&engines=startpage" \
  | jq -r '.results[].url'
```

Operator behaviour (SearXNG passes the query through verbatim, so support is per-engine):

- `filetype:txt llms-full` — works via `startpage`. One clean run returned 20/20 results whose
  path ended in `/llms-full.txt`; `filetype:txt llms` returned 19/19.
- `inurl:` / `intitle:` — not supported. `startpage` strips them, `google cse` ignores them
  (Programmable Search does not implement `inurl:`).
- `site:` — works alone; combined with other operators it can produce
  `startpage: parsing error`.
- Keenable (`web_search` default backend) honours `site:` only. `inurl:`, `intitle:`, `filetype:`
  are silently ignored — it POSTs `{query, max_results}` straight to the API, no operator layer.

Check engine health before blaming the query. **Always read `unresponsive_engines`:**

```bash
curl -s "http://localhost:8080/search?q=...&format=json" | jq '.unresponsive_engines'
```

A dork that returns 0 usually means the engine died, not that the web is empty. Observed the
same day as the 20/20 run: `startpage: parsing error`, `google cse: too many requests`,
`brave: Suspended`, `duckduckgo: CAPTCHA`. Re-run later instead of rewriting the query.

## 3. GitHub filename sweep (best signal-to-noise for bulk)

```bash
gh api "search/code?q=filename:llms-full.txt&per_page=1" --jq .total_count
gh api "search/code?q=filename:llms.txt&per_page=1" --jq .total_count
```

- `filename:llms-full.txt` → **59,328** (2026-11-04).
- `filename:llms.txt` → **192,000**, which is GitHub's result ceiling, not a real count. Treat any
  value at exactly 192,000 as "at least this many".

Narrow with `in:path`, `language:Markdown`, `org:`, `repo:`, `extension:`. Requires an
authenticated `gh` (here: account `gwyntel-git`, token in `~/.hermes/.env`); a placeholder token
returns `401 Bad credentials`. Plain DuckDuckGo HTML and Bing scraping return nothing against
GitHub — use the API.

## 4. Registries (curated, small)

- `https://llmstxt.org/` — the spec plus a partial source list
- `https://directory.llmstxt.cloud/`
- `https://llmstxt.site/`

## Validation gate — HTTP 200 is not proof

Reject a hit unless all of these hold:

1. `Content-Type` is `text/plain` or `text/markdown`. `text/html` means an SPA shell echoing the
   path back. 5 of 20 dork hits were this.
2. The body opens with `# ` — or YAML frontmatter, which some generators emit
   (`developers.cloudflare.com/llms-full.txt` does). It must not open with `# Page Not Found`.
3. `%{url_effective}` still ends in the filename you asked for.
4. Size is plausible: `llms-full.txt` ≥ `llms.txt`. Identical bytes mean you were served the
   index.
5. Exactly 401 bytes of "# Page Not Found" is a known Cloudflare shim served with **200**.

```bash
curl -sL -A 'Mozilla/5.0' -D- -o body.txt "$URL" | grep -iE '^(HTTP|content-type|location)'
head -c 200 body.txt; wc -c body.txt
```

## Pitfalls, each one cost a real run

| Symptom | Cause | Fix |
|---|---|---|
| 200 with HTML | SPA shell renders the path as a route | check `Content-Type`, not status |
| 200 with 0 bytes | bare `301` to another path, read without `-L` | follow redirects, print final URL |
| `llms-full.txt` identical to `llms.txt` | server redirects the full variant to the index | compare sizes/hashes |
| `# Page Not Found`, 401 bytes, 200 | CDN shim for a missing page | body check |
| dork returns 0, no error | engine suspended or parsing error | inspect `unresponsive_engines` |
| 403 to curl, fine in a browser | UA gating | add a browser UA or use camofox |
| GitHub count exactly 192,000 | API result ceiling | scope the query further |

## Verified-live seed list (2026-11-04, via `filetype:txt` dork)

Real corpus confirmed: `platform.claude.com/llms-full.txt`, `modal.com/llms-full.txt`,
`bun.com/llms-full.txt`, `docs.modular.com/llms-full.txt`, `pydantic.dev/docs/ai/llms-full.txt`,
`docs.readthedocs.com/llms-full.txt`, `resend.com/docs/llms-full.txt`,
`docs.creem.io/llms-full.txt`, `www.prisma.io/llms-full.txt`, `developers.cloudflare.com/llms-full.txt`,
`jfrog.com/llms.txt`, `www.windmill.dev/llms.txt`, `docs.openwebui.com/llms.txt`,
`www.okta.com/llms.txt`, `docs.x.ai/llms.txt`, `mariadb.com/llms.txt`, `arize.com/docs/llms.txt`,
`help.yahooinc.com/llms.txt`, `noritz.com/llms.txt`.

Fake hits to expect from the same dork: `eventcatalog.dev`, `infrasity.com`, `opendoc.alipay.com`,
`ark-ui.com`, `heroui.com` (HTML shells) and `bloggers.tools` (403 to non-browser UA).
