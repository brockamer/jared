# PII Pre-Flight Redactor

A runtime check that scans issue and comment bodies for content matched against gitignored claude-shaped local files. Refuses to post on hits. Closes the gap that jared's `gh` / MCP API calls bypass any local pre-commit hook protecting file-based commits.

## What it scans

The redactor looks under the project root for gitignored claude-shaped files at:

- `CLAUDE.local.md`
- `.claude/CLAUDE.local.md`
- `.claude/local/*.md`

Files are only considered when the project root is a git repo (has a `.git/` directory). Without git, the allowlist semantics break, so the redactor returns clean rather than flagging everything inconsistently.

**v1 scope: only the three patterns above.** A future change may extend this to arbitrary paths matched by `.gitignore` whose path component contains the literal substring `claude` (case-insensitive) — that broader rule is in the design spec but is not implemented yet. If you keep private claude-content under a non-standard path, move it to one of the three patterns above for v1 protection.

## What counts as a "phrase"

Each line of each scanned file is a candidate phrase if — after stripping markdown leaders (`-`, `*`, `>`, `#`, `|`, backticks, leading whitespace) — it has:

- at least 3 whitespace-separated words, AND
- at least 20 characters total.

Shorter content (single words, short tokens, generic markdown structure) is ignored. The thresholds catch rich content like `"the deploy host is internal-foo-7.corp.example"` while ignoring `"# Section"`, `"- foo"`, or `"hostname"`.

## Allowlist semantics

A phrase that appears in *any* tracked file is already public — the redactor does not flag it. The check is `phrase in <concatenated tracked file contents>` via one `git ls-files` call per `jared` invocation (cached process-locally).

This means: if you intentionally documented something publicly in `README.md` and the same phrase happens to appear in `CLAUDE.local.md`, the redactor will not flag it. Conversely, content that lives only in the gitignored file is the protected surface.

## What happens on a hit

`jared file` and `jared comment` both run the pre-flight immediately after resolving the body and before any `gh` call. On a non-clean report:

- Exit code: 2
- Stderr: a structured diff naming each match — line number in the body, the matched phrase, and which gitignored file it came from
- No issue is created; no comment is posted

## How to bypass intentionally

Two ways:

1. **Re-issue with private content removed.** Edit the body to drop the phrase. This is the right move when the phrase is genuinely private.
2. **Add the matched phrase to a tracked file.** If the phrase is something you'd publish anyway (a public deploy URL, a documented hostname), commit it to `README.md` (or any tracked file) so the allowlist picks it up. Re-run the call.

## What it does NOT do

- **No silent edits.** The redactor refuses; it never modifies the body. Silent edits are surprising; a paraphrase that survives redaction is still a leak.
- **No on-disk cache.** Cache lives in process memory and dies with the `jared` invocation. Re-scan cost is negligible (a few milliseconds for typical local files).
- **No configurable thresholds (yet).** v1 ships with hardcoded `MIN_WORDS=3, MIN_CHARS=20`. If false positives flood, the thresholds will become configurable via `docs/project-board.md`.
- **No arbitrary `.gitignore`-pattern matching (yet).** v1 scans only the three fixed patterns above. The design spec calls for extending this to any `.gitignore`-matched path containing `claude` (case-insensitive); deferred to a future change.
- **Not a replacement for the pre-commit hook.** The pre-commit hook protects file-system commits; the redactor protects API writes. Both are required for full coverage.

## See also

- `references/operations.md` — Cautions section, cross-reference
- `SKILL.md` § "The lane" — the doctrine the redactor enforces in code
- Issue #102 — design and acceptance
