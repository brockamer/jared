# PII Pre-Flight Redactor

A runtime check that scans issue and comment bodies for content matched against the repo's gitignored private files. Refuses to post on hits, and says so when it had nothing to scan. Closes the gap that jared's `gh` / MCP API calls bypass any local pre-commit hook protecting file-based commits.

## What it scans

The redactor looks under the project root for the repo's private sources:

- `CLAUDE.local.md`
- `.claude/CLAUDE.local.md`
- `.claude/local/*.md`
- **any gitignored `*.md` file at the repo root** (#443) — for example a `<project>-prompt.md` that a repo's own `AGENTS.md` names as private. Git decides what counts as ignored (`git check-ignore`), so `.gitignore`, `.git/info/exclude` and the global excludes file all apply, and a tracked file never counts.

Files are only considered when the project root is a git repo (has a `.git/` directory). Without git, the allowlist semantics break, so nothing is scanned — and the report says so (see "When nothing is scanned").

**Root level only.** A gitignored markdown file in a subdirectory is not scanned, except under `.claude/local/`. Walking ignored trees would read `.venv/` and similar on every call. If you keep private content deeper in the tree, move it to the repo root (gitignored) or to `.claude/local/`.

## What counts as a "phrase"

Each line of each scanned file is a candidate phrase if — after stripping markdown leaders (`-`, `*`, `>`, `#`, `|`, backticks, leading whitespace) — it has:

- at least 3 whitespace-separated words, AND
- at least 20 characters total.

Shorter content (single words, short tokens, generic markdown structure) is ignored. The thresholds catch rich content like `"the deploy host is internal-foo-7.corp.example"` while ignoring `"# Section"`, `"- foo"`, or `"hostname"`.

## Allowlist semantics

A phrase that appears in *any* tracked file is already public — the redactor does not flag it. The check is `phrase in <concatenated tracked file contents>` via one `git ls-files` call per `jared` invocation (cached process-locally).

This means: if you intentionally documented something publicly in `README.md` and the same phrase happens to appear in `CLAUDE.local.md`, the redactor will not flag it. Conversely, content that lives only in the gitignored file is the protected surface.

## What happens on a hit

`jared file`, `jared comment` and `jared close --body*` all run the pre-flight immediately after resolving the body and before any `gh` call. When the report has matches:

- Exit code: 2
- Stderr: a structured diff naming each match — line number in the body, the matched phrase, and which gitignored file it came from
- No issue is created; no comment is posted

## When nothing is scanned

A scan of zero files proves nothing, so it is never reported as clean (#443). `RedactionReport` has three outcomes: `matches` non-empty; `clean` (at least one file scanned, no match); or `vacuous` (no file scanned), with `unscanned_reason` set to `no-git` or `no-private-files`. A caller that gates on `clean` alone therefore fails closed.

`jared file`, `jared comment` and `jared close` still post on a vacuous scan — refusing would block every repo that has no private file — but first print a warning to stderr:

```
warning: pre-flight scanned 0 private files — this body was not checked for private content.
```

followed by one line naming the reason and the fix. **Relay that warning to the operator.** It is the only sign that the post went out unchecked; a repo that does hold private context under an unrecognised path needs it moved to a scanned location.

## Checking a draft without posting — `jared pre-flight`

Only `jared file`, `jared comment` and `jared close` run the pre-flight themselves. **Every other route that puts a body on the board must run `jared pre-flight` on the draft first**: `gh issue edit --body-file` (`/jared-groom`), `gh api -X PATCH` (`/jared-audit`), `capture-context.py --current-state` / `--decision` (`/jared-wrap`), and MCP tools such as `issue_write` or `add_issue_comment`. Run it on the text you are adding, before the operator approves the write:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared pre-flight --body-file <draft>   # or --body "<text>", or --body-file -
```

| Exit | Meaning | Do |
|---|---|---|
| 0 | Private sources scanned, no match. Stdout: `OK: pre-flight scanned N private file(s); no matches.` | Proceed to approval. |
| 2 | A match. Stderr carries the diff. | Do not post. Show the operator the flagged lines and revise the draft. |
| 3 | Nothing was scanned. Stderr carries the warning. | Tell the operator the draft was not checked, and let them decide whether to post. |

It needs no board and runs from anywhere inside the repo (it walks up to the `.git/` root, like the posting commands).

## How to bypass intentionally

Two ways:

1. **Re-issue with private content removed.** Edit the body to drop the phrase. This is the right move when the phrase is genuinely private.
2. **Add the matched phrase to a tracked file.** If the phrase is something you'd publish anyway (a public deploy URL, a documented hostname), commit it to `README.md` (or any tracked file) so the allowlist picks it up. Re-run the call.

## What it does NOT do

- **No silent edits.** The redactor refuses; it never modifies the body. Silent edits are surprising; a paraphrase that survives redaction is still a leak.
- **No on-disk cache.** Cache lives in process memory and dies with the `jared` invocation. Re-scan cost is negligible (a few milliseconds for typical local files).
- **No configurable thresholds (yet).** v1 ships with hardcoded `MIN_WORDS=3, MIN_CHARS=20`. If false positives flood, the thresholds will become configurable via `docs/project-board.md`.
- **No deep `.gitignore` walk.** Beyond the three fixed patterns, only gitignored markdown at the repo root is scanned. The archived design spec's rule — any `.gitignore`-matched path containing `claude` — was never built, and would not have caught a root-level private file named for its project (#443).
- **Not a replacement for the pre-commit hook.** The pre-commit hook protects file-system commits; the redactor protects API writes. Both are required for full coverage.

## See also

- `references/operations.md` — Cautions section, cross-reference
- `SKILL.md` § "The lane" — the doctrine the redactor enforces in code
- Issue #102 — design and acceptance
- Issue #443 — root-markdown discovery, the vacuous outcome, and `jared pre-flight`
