# PII Pre-Flight Redactor

A runtime check that scans issue and comment bodies for content matched against the repo's gitignored private files. Refuses to post on hits, and says so when it had nothing to compare. Closes the gap that jared's `gh` / MCP API calls bypass any local pre-commit hook protecting file-based commits.

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

A phrase matches only when the body contains the whole cleaned line. A list of short names, one per line, therefore gives no phrase at all. To check short names, list them as terms (next section). A file that gives no phrase and no term is not checked: the report is vacuous (#526), or, when another file was compared, the file is named in a warning (see "When nothing is scanned").

A term bullet (next section) is never a phrase, however long it is. It follows the term rule only.

## Listed terms — `## Pre-flight terms`

A phrase cannot catch a name or a place: a draft names a person without repeating a whole line of your notes. For those, list terms (#528). Put a `## Pre-flight terms` heading in any private source that pre-flight already scans, and write one term per bullet:

```markdown
## Pre-flight terms

- Jane Doe
- Orchard Lane
- internal-foo-7
```

- **Section.** The bullets under the heading, up to the next heading, are terms. Any heading level works (`##`, `###`), and the heading text is case-insensitive. A line in the section that is not a bullet follows the phrase rule. A file can have more than one terms section. No new file pattern: the heading goes in a file from "What it scans".
- **Floor.** A term needs 3 or more characters. Shorter terms are ignored. A multi-word term is one term.
- **Match.** Case-sensitive and whole-token: the character on each side of the match is not a letter or a digit, or is the edge of the line. `Jane Doe's team` matches the term `Jane Doe`; `Janet Doerr` does not. The body is checked one line at a time.
- **Allowlist.** A term that a tracked file holds as a whole token is public and is dropped (see "Allowlist semantics").
- **Not in `docs/project-board.md`.** That file is tracked, so a list there is published. The list belongs in the private file, next to the notes that hold the same names.

**Accepted false negatives.** The match is exact, so these pass:

- a different case — `jane doe` does not match `Jane Doe`;
- a plural or an inflected form — `Jane Does`, `Orchard Lane's` matches but `Orchard Lanes` does not;
- a term split across two lines of the body.

List each form you want to catch as its own term. **"Clean" means that no listed term and no copied line occurs in the body. It does not mean that the body holds no private content.**

## Allowlist semantics

A phrase that appears in *any* tracked file is already public — the redactor does not flag it. The check is `phrase in <concatenated tracked file contents>` via one `git ls-files` call per `jared` invocation (cached process-locally).

A term uses the stricter whole-token test against the same content. A substring test would drop the term `Jane` because a tracked file says `Janeway`, and a short name inside a longer tracked word is common. A long line cannot collide that way, so phrases keep the substring test.

This means: if you intentionally documented something publicly in `README.md` and the same phrase happens to appear in `CLAUDE.local.md`, the redactor will not flag it. Conversely, content that lives only in the gitignored file is the protected surface.

## What happens on a hit

`jared file`, `jared comment` and `jared close --body*` all run the pre-flight immediately after resolving the body and before any `gh` call. When the report has matches:

- Exit code: 2
- Stderr: a structured diff naming each match — line number and text in the body, and which private file it came from. A term match also names the term, because a term can sit anywhere in a long line: `↳ matches CLAUDE.local.md (term "Jane Doe")`
- No issue is created; no comment is posted

## When nothing is scanned

A check that compared nothing proves nothing, so it is never reported as clean (#443). `RedactionReport` has three outcomes: `matches` non-empty; `clean` (private phrases or terms compared, no match); or `vacuous` (nothing compared), with `unscanned_reason` set to one of:

| Reason | Cause |
|---|---|
| `no-git` | The project root has no `.git/` directory, so no file counts as gitignored. |
| `no-private-files` | A git repo, but no private source was found. |
| `no-usable-phrases` | Private files were found, but they give no phrase and no term: every line is under the phrase floor, every term is under the term floor, or a tracked file also holds it (#526, #528). Only this reason comes with a non-empty `scanned_files`. The name predates terms. |

A caller that gates on `clean` alone therefore fails closed.

`jared file`, `jared comment` and `jared close` still post on a vacuous scan — refusing would block every repo whose private file holds only short lines, or that has none — but first print a warning to stderr. With no private file found:

```
warning: pre-flight scanned 0 private files — this body was not checked for private content.
```

followed by one line naming the reason and the fix. With private files that gave no phrase and no term:

```
warning: pre-flight found no usable phrase or term in 1 private file — this body was not checked for private content.
```

followed by one line per file, one line stating the phrase rule, and one line naming the `## Pre-flight terms` heading and the term rule.

**A file that adds nothing.** When one private file gives a phrase or a term and another gives neither, the report is still clean — something was compared — and the exit code does not change. The second file's contents were never compared, though, so the call prints (#528):

```
warning: pre-flight got nothing to compare from 1 of 2 private files — this body was checked against the others only.
```

followed by one line per such file and the same two rule lines. The usual cause is a list of short names with no terms heading. Without this line, that list would pass as checked because another file was.

**Relay any `warning: pre-flight` line to the operator.** It is the only sign that the post went out unchecked, or checked against less than the operator expects. Every pre-flight warning starts with that prefix. A repo that holds private context under an unrecognised path needs it moved to a scanned location; short names need a `## Pre-flight terms` section.

## Checking a draft without posting — `jared pre-flight`

Only `jared file`, `jared comment` and `jared close` run the pre-flight themselves. **Every other route that puts a body on the board must run `jared pre-flight` on the draft first**: `gh issue edit --body-file` (`/jared-groom`), `gh api -X PATCH` (`/jared-audit`), `capture-context.py --current-state` / `--decision` (`/jared-wrap`), and MCP tools such as `issue_write` or `add_issue_comment`. Run it on the text you are adding, before the operator approves the write:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared pre-flight --body-file <draft>   # or --body "<text>", or --body-file -
```

| Exit | Meaning | Do |
|---|---|---|
| 0 | Private phrases or terms compared, no match. Stdout: `OK: pre-flight scanned N private file(s); no matches.` Stderr names any private file that gave nothing to compare. | Proceed to approval. Relay a stderr warning. |
| 2 | A match. Stderr carries the diff. | Do not post. Show the operator the flagged lines and revise the draft. |
| 3 | Nothing was checked: no private file was found, or none gave a usable phrase or term. Stderr carries the warning. | Tell the operator the draft was not checked, and let them decide whether to post. |

It needs no board and runs from anywhere inside the repo (it walks up to the `.git/` root, like the posting commands).

## How to bypass intentionally

Two ways:

1. **Re-issue with private content removed.** Edit the body to drop the phrase or term. This is the right move when it is genuinely private.
2. **Add the matched phrase or term to a tracked file.** If it is something you'd publish anyway (a public deploy URL, a documented hostname, a name already credited in the README), commit it to `README.md` (or any tracked file) so the allowlist picks it up. A term must appear there as a whole token. Re-run the call.

## What it does NOT do

- **No silent edits.** The redactor refuses; it never modifies the body. Silent edits are surprising; a paraphrase that survives redaction is still a leak.
- **No on-disk cache.** Cache lives in process memory and dies with the `jared` invocation. Re-scan cost is negligible (a few milliseconds for typical local files).
- **No configurable thresholds.** The phrase floor (3 words, 20 characters) and the term floor (3 characters) are fixed. The configurable part is the term list (#528), and it lives in the private file, never in `docs/project-board.md`, which is tracked.
- **No hashed terms.** Pre-flight guards what is posted, not what is on disk, and the same names are already plain text in the same private file. Hashing would also break the tracked-content allowlist.
- **No external check command.** A repo-supplied setting that runs code is a supply-chain risk in a marketplace plugin.
- **No fuzzy match.** No case folding, stemming or plural handling — see "Accepted false negatives".
- **No deep `.gitignore` walk.** Beyond the three fixed patterns, only gitignored markdown at the repo root is scanned. The archived design spec's rule — any `.gitignore`-matched path containing `claude` — was never built, and would not have caught a root-level private file named for its project (#443).
- **Not a replacement for the pre-commit hook.** The pre-commit hook protects file-system commits; the redactor protects API writes. Both are required for full coverage.

## See also

- `references/operations.md` — Cautions section, cross-reference
- `SKILL.md` § "The lane" — the doctrine the redactor enforces in code
- Issue #102 — design and acceptance
- Issue #443 — root-markdown discovery, the vacuous outcome, and `jared pre-flight`
- Issue #526 — a private file that gives no usable phrase is vacuous, not clean
- Issue #528 — `## Pre-flight terms`, the whole-token match, and the warning for a private file that adds nothing
