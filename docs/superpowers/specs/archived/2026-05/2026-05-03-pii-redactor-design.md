---
**Shipped in #102 on 2026-05-03. Final decisions captured in issue body.**
---

# PII Pre-Flight Redactor — Design Spec

**Issue:** brockamer/jared#102
**Status:** Spec
**Date:** 2026-05-03

## Goal

A runtime pre-flight in `lib/board.py` that scans body content (issue bodies and comments) for matches against gitignored claude-shaped local files (`CLAUDE.local.md`, `.claude/local/*.md`, anything matched by `.gitignore` containing the literal substring `claude`) and refuses to post on hits. Closes the gap that jared's `gh` / MCP API calls bypass any local pre-commit hook protecting file-based commits — so a careless paraphrase of `CLAUDE.local.md` content (real names, internal IDs, deploy hostnames, contact info) can land in a public GitHub issue body with no signal to the operator.

This is the runtime enforcement of the doctrine shipped in #97: *jared writes only board state, reads everything else.* The redactor is the missing fence on the read-only side.

## Architecture

### Module-level pure function

```python
@dataclass
class RedactionMatch:
    line_no: int           # 1-based line number in the body
    line_text: str         # full line, for context display
    matched_phrase: str    # the phrase (substring) that hit
    source_file: Path      # which gitignored claude-shaped file it came from


@dataclass
class RedactionReport:
    matches: list[RedactionMatch]
    scanned_files: list[Path]   # for "no matches because no files scanned" diagnostics

    @property
    def clean(self) -> bool:
        return not self.matches


def pre_flight_check(body: str, project_root: Path) -> RedactionReport:
    """Scan body against gitignored claude-shaped files; return matches.

    Pure function — no I/O on caller's behalf, no exit, no print. Caller
    decides what to do with a non-clean report (typically: print diff,
    return 2, do not invoke gh).
    """
```

`pre_flight_check` is added to `lib/board.py` alongside `resolve_body` (the seam established in #98 / PR #99). Both are pure helpers shared across `_cmd_file` and `_cmd_comment`.

### Caller integration

Both write entry points in the `jared` CLI (`_cmd_file`, `_cmd_comment`) gain the same shape immediately after `resolve_body()`:

```python
body = resolve_body(args.body, args.body_file)
report = pre_flight_check(body, project_root=Path.cwd())
if not report.clean:
    print_redaction_diff(report, file=sys.stderr)
    return 2
# ... existing tempfile staging + gh call
```

`print_redaction_diff` is a sibling helper in `lib/board.py` that formats the report for stderr.

### Output format (refuse-with-diff)

```
error: pre-flight redaction check failed — body references content from
gitignored claude-shaped local files. Refusing to post.

  3 matches across 2 files:
    line 12: "...the deploy host is internal-foo-7..."
      ↳ matches CLAUDE.local.md
    line 18: "...credentials at /opt/secrets/..."
      ↳ matches .claude/local/ops.md
    line 22: "...contact joe.smith@..."
      ↳ matches CLAUDE.local.md

  next steps:
    1. Re-issue the call with private content removed.
    2. OR add the matched phrase to a tracked file if it's intentionally public.
```

Exit code 2 is consistent with the rest of `_cmd_file`'s diagnostic-error contract.

## Resolved design questions

These were the five open questions in #102's body. Each is fixed in this spec:

### Q1 — Ergonomics: refuse-with-diff (no silent edits)

When the report is non-clean, the caller prints the diff and exits 2. The redactor never edits the body itself.

Rationale: silent edits are surprising — a session that thinks it filed an issue with content X has actually filed content Y, and the surprise surfaces only when the operator reads the posted issue. A paraphrase that survives redaction is still a leak. The redactor's job is to be a fence, not a sanitizer.

### Q2 — Allowlist scope: any string already present in a tracked file

Compute by running `git ls-files` to enumerate tracked files, then for each candidate phrase from a gitignored claude-shaped file, check whether that phrase appears in *any* tracked file's content. If so, it's already public — don't flag it. Self-maintaining (no manual allowlist drift), accurate (committed = already public), and robust (a project that intentionally documents its hostname in `README.md` won't get false positives even if the same hostname appears in `CLAUDE.local.md`).

Implementation: collect tracked-file contents into one big string at scan time, do `phrase in tracked_content` per candidate. One bulk read, no per-phrase subprocess.

### Q3 — Matching strategy: line-anchored multi-word phrases

Extract every line from gitignored claude-shaped files matching:
- ≥ 3 whitespace-separated words after stripping markdown punctuation (`-`, `*`, `>`, `#`, `|`, backticks, etc.) from the line start
- ≥ 20 characters total in the cleaned line

These thresholds catch rich content like `"the deploy host is internal-foo-7.corp.example"` and `"Daniel's emergency contact is +1-555-..."` while ignoring:
- generic single words (`"hostname"`, `"credential"`)
- short tokens common in any document (`"the user"`, `"daniel"`)
- markdown structure (`"# Section"`, `"- item"` of a single-word value)

Matching is case-sensitive substring search (`phrase in body`). Case-sensitivity reduces false positives for English prose where capitalization often distinguishes private content from generic content.

### Q4 — Performance budget: scan-once-per-process

Cache the extracted phrases + tracked-content corpus in a process-local dict keyed on `project_root`. First call pays the I/O cost (typically a few milliseconds for normal `CLAUDE.local.md` sizes); subsequent calls in the same `jared` invocation are O(1) lookups against the cache.

No on-disk cache. Scope to in-process for v1 simplicity. The cache is invalidated implicitly by process exit, which matches `jared` invocation lifetime.

### Q5 — Sensitivity tuning: hardcoded thresholds for v1

Ship with `MIN_WORDS = 3`, `MIN_CHARS = 20`. If false positives flood, raise. If real content slips through, lower. Configurability via `docs/project-board.md` is deferred — hardcoded behavior is testable and consistent across projects, and v1 needs empirical data before adding a config knob.

## File scope: gitignored claude-shaped files

Match files at any of:

- `<project_root>/CLAUDE.local.md`
- `<project_root>/.claude/CLAUDE.local.md`
- `<project_root>/.claude/local/*.md`
- Any path matched by `<project_root>/.gitignore` whose path component contains the literal substring `claude` (case-insensitive)

If `<project_root>` isn't a git repo (no `.git/` directory), return an empty report (`scanned_files=[]`, `matches=[]`). The redactor is git-aware by design — without a git repo, there's no notion of "tracked" vs "gitignored," so the allowlist semantics break. Better to return clean than to flag everything or nothing inconsistently.

## Test plan

### Unit tests for `pre_flight_check`

- `test_pre_flight_check_empty_body_clean`
- `test_pre_flight_check_no_git_repo_returns_empty_report`
- `test_pre_flight_check_no_claude_files_clean`
- `test_pre_flight_check_match_in_CLAUDE_local_flagged`
- `test_pre_flight_check_match_in_dot_claude_local_md_flagged`
- `test_pre_flight_check_short_phrase_ignored` — 2-word phrase doesn't trigger
- `test_pre_flight_check_short_line_ignored` — 19-char line doesn't trigger
- `test_pre_flight_check_allowlist_skips_phrase_in_tracked_README` — same phrase in tracked file → not flagged
- `test_pre_flight_check_caches_per_project_root` — second call to same root re-uses scan results

### Unit test for `print_redaction_diff`

- `test_print_redaction_diff_format` — pinned output format

### Integration tests

- `test_cmd_file_refuses_on_dirty_report` — non-clean body → rc=2, no gh call
- `test_cmd_file_proceeds_on_clean_report` — clean body → normal flow
- `test_cmd_comment_refuses_on_dirty_report`
- `test_cmd_comment_proceeds_on_clean_report`

Total: ~13 new tests across `tests/test_lib_board.py` (new file or existing) and `tests/test_cmd_file.py` / `tests/test_cmd_comment.py` extensions.

## Sequence

1. **Phase 1 — `pre_flight_check` + `print_redaction_diff` + dataclasses in `lib/board.py`.** TDD on the unit tests above (~10 tests). No CLI integration yet.
2. **Phase 2 — Wire into `_cmd_file` and `_cmd_comment`.** Add the integration tests (~4). Existing tests must remain green; the redactor must not trigger when bodies don't reference local-claude content.
3. **Phase 3 — Documentation.** New `references/pii-pre-flight.md` describing the matching rules, the allowlist semantics ("anything in a tracked file is public"), and how to bypass intentionally (move the content to a tracked file, or rephrase the body).
4. **Phase 4 — Live smoke.** Hand-craft a `CLAUDE.local.md` fixture in this repo with a leaky-looking phrase, run `jared file --body "<phrase>"` and confirm the refuse-and-diff. Run `jared file --body "<safe content>"` and confirm normal flow. Pass `--body-file -` with the same content variations to confirm parity.

## Documentation Impact

- **NEW:** `skills/jared/references/pii-pre-flight.md` — full operator reference for the redactor.
- **UPDATE:** `skills/jared/SKILL.md` § "The lane" — replace the future-tense reference to #102 with present-tense doctrine pointing at the new reference doc.
- **UPDATE:** `skills/jared/references/operations.md` — cross-reference the new doc from the Cautions section.
- **UPDATE:** `commands/jared-file.md`, `commands/jared-wrap.md` — short note that body content is pre-flight-scanned for private claude-content references.

## Self-review checklist

- [ ] Phase 1 tests RED before implementation; each watched fail correctly
- [ ] Phase 2 integration tests RED before wiring (no gh call assertion)
- [ ] All existing 242 tests remain green after each phase
- [ ] `ruff check` + `ruff format --check` + `mypy --strict` clean
- [ ] Phase 3 doc lands with Phase 2 (not separate)
- [ ] Phase 4 smoke is documented in the PR body, including the test phrases used
- [ ] PR body explicitly notes the deferred items (auto-redaction; on-disk cache; configurable thresholds)

## Out of scope (deferred)

- **Auto-redaction / silent edits.** Q1 explicitly resolved against. The redactor refuses; the caller decides what to do.
- **On-disk caching across `jared` invocations.** Q4 — in-process cache is sufficient for v1. Add an on-disk SHA-keyed cache only if profiling shows the scan cost is meaningful.
- **Configurable thresholds via `docs/project-board.md`.** Q5 — empirical data first, knob second.
- **Sibling rule for `claude-md-improver`.** #97 item 3 sub-question — out of jared's lane. File separately if observed.
- **Multi-language phrase support / non-English prose.** v1 assumes English-shaped content. International projects with non-Latin local files may need different word-boundary logic; not blocking.
