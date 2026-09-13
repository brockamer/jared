# `voice: ste` — ASD-STE100 dialogue mode — design

**Issue:** #374 — "feat(voice): add `voice: ste` — render Jared's dialogue in ASD-STE100 Simplified Technical English"
**Date:** 2026-09-13
**Status:** design approved in session (operator chose the recommended position on all three open questions); plan to follow
**Related:** #369 (shares `references/voice.md` through F58 and F59); #114 and F9 (the precedent this design must not repeat)

## 1. What this is

The `voice:` bullet in `docs/project-board.md` § `## Jared config` gets a third value, `ste`.
Under `ste`, Jared renders every dialogue surface in ASD-STE100 Simplified Technical English.
The two existing values are unchanged: `enabled` renders the Jared Dunn character voice,
`disabled` renders unconstrained plain technical prose.

`ste` is not a softer `disabled`. `disabled` removes the character; the prose that remains
has no rule set. `ste` is a controlled language with a published specification: approved
words with one meaning each, active voice, sentence-length caps, no `-ing` verb forms, one
instruction per sentence, vertical lists for complex content. A reader cannot reach `ste`
from `disabled` by deletion alone.

The operator intends to use `ste` as their default on this board.

## 2. Governing constraint — doctrine only

`voice:` is not parsed in Python and `ste` will not be either. Verified 2026-09-13:
`grep voice skills/jared/scripts/lib/board.py` returns nothing; the only Python reference
is `bootstrap-project.py:862`, which emits the bullet into a generated convention doc and
never reads it back. Twelve prose surfaces branch on the bullet directly.

This design adds text to those surfaces and to one new reference file. It adds no
`Board.voice` field, no parse test, no CLI gate. CLAUDE.md § "Evolving Jared's discipline"
is the rule; #114 (a parsed field nothing read, reverted two phases later) and F9 (same
shape, deletion tracked on #369) are the precedents. A reviewer who asks for a parser has
found a design drift, not a gap.

## 3. Decisions on the three open questions

### 3a. Where the spec lives — a new file, `references/voice-ste.md`

`references/voice.md` is 216 lines of character material: personality traits, ten style
rules, sentence starters, anchor quotes from the show, six worked situations. STE rules do
not belong beside show quotes, and a reader who loads one file should not have to skip the
other half. A separate file also loads on demand only when the bullet says `ste`.

`voice.md` changes in three places only: its kill-switch paragraph names the third value
and points at the new file; its boundary-table row for drift-reconcile prompts is corrected
(F58); its voice-OFF batch-script row gains `capture-context.py` (F59). The F58 and F59
fixes are their own commit so #369 can see them as resolved.

### 3b. How much structure `ste` mandates — within a section, never across sections

Every stub's output template has a section skeleton: an opening line, named sections in a
fixed order, an approval question at the end. The stubs state that this skeleton is the
cross-session shape ("the reader scanning the same surface across sessions benefits from the
consistent shape"). `ste` keeps the skeleton. Section names, section order, and the
"(nothing)" collapse rule are unchanged.

Inside a section, STE rules apply in full:

- Topic sentence first. The first sentence states the finding; the sentences after it give
  the evidence.
- A vertical list for three or more parallel items.
- At most six sentences per paragraph. A longer section becomes two paragraphs or a list.
- Each "one-line warm framing" slot becomes one statement of fact about the board.

Reorganize within a section. Do not merge sections, split sections, or reorder them.

### 3c. Rule or worked example — rules primary, examples secondary

A character voice has no rule set, so `voice.md` must carry examples. ASD-STE100 has a
published rule set, so `voice-ste.md` states the rules first. The examples then show the
rules applied to jared's own shapes, and a diagnostic checklist closes the file, mirroring
`voice.md` § "Diagnostic — when the voice has slipped".

The paired examples reuse the in-voice texts that `voice.md` already carries as the "before"
half. No new voice text is written for this feature. The pairs are:

| `voice.md` situation | `ste` example |
|---|---|
| Situation 1 — `/jared` status report | new |
| Situation 2 — drift-reconcile prompt | new |
| Situation 4 — error mode | new |
| Situation 5 — `/jared-start` announce | new |

Situations 3 (indirect-action trigger) and 6 (`/jared-init` introduction) are covered by the
rules and the aside rule; they do not need a pair.

## 4. The fixture

The issue body said the Joplin note "Structural review — 2026-09-12" holds the review twice,
once in voice and once in STE. It does not. The note holds one rendering, with no voice
markers, and that rendering is not strict STE. The claim is corrected on the issue body in
this session.

The long-form fixture is the Joplin note **"Recommendations (ASD-STE100) — 2026-09-11"**
(`NOTEBOOK`, 266 lines). It uses defined terms, NOTE and CAUTION notices
before the step they apply to, one instruction per step, and a "Result:" line after each
procedure. `voice-ste.md` cites it by title and notebook.

The verification runs in § 8 produce the feature's own fixture: two slash-command outputs
rendered under `ste` on this board, saved to Joplin as "Fixture — `voice: ste` — 2026-09-13".

## 5. The `ste` rendering contract

This is the content of `references/voice-ste.md`, in summary. The reference file is the
authoritative statement.

### 5.1 Rules Jared applies

Source: ASD-STE100, Issue 8. Rule numbers are not cited; the rules are stated by effect.

- Use an approved word for each meaning, and use each word with one meaning.
- Use a technical name or a technical verb where the domain has one. Jared's technical names
  are listed in § 5.3.
- Write procedures in the imperative. Give one instruction per sentence.
- Use the active voice. The passive is permitted in a description only when the agent is
  unknown or unimportant.
- Use approved verb forms only: infinitive, imperative, past tense, past participle as an
  adjective, and future. Do not use an `-ing` form as a verb or a noun.
- A procedural sentence has at most 20 words. A descriptive sentence has at most 25 words.
- A paragraph has at most six sentences and one topic. The topic sentence is first.
- Do not omit words to make a sentence shorter. Keep articles and the verb.
- Put a warning or a caution before the step it applies to. Put a note where it helps.
- Use a vertical list for three or more parallel items, and a table for parallel data.
- Do not use slang, idiom, metaphor, or stylistic writing.

### 5.2 The aside rule

The stubs for `/jared-init`, `/jared-reshape`, `/jared-wrap`, `/jared-start`, `/jared-groom`,
`/jared-audit`, `/jared-stage`, `/jared-file` and `/jared` each instruct a warm framing line,
an aside, or both. Under `ste` those instructions are void. STE forbids stylistic writing; an
aside cannot be rendered more plainly and survive. Each stub carries an explicit `ste`
sentence that says so, next to the instruction it voids. The restraint rules that govern
asides ("one per response", "never verbatim across sessions") are void with them.

### 5.3 Passthrough — what `ste` does not rewrite

Four classes of text pass through `ste` unchanged. The same four classes pass through the
character voice unchanged today; `ste` adds no class and removes none.

| Class | Examples | Why |
|---|---|---|
| Machine-fixed strings | `degraded: <feature> unavailable on <backend> — <instead>`; `OK: set Status=In Progress on issue #374`; `GhInvocationError`; every CLI stdout and stderr line | Consistency anchors and grep targets (F11, F27, F53, F57 record what drift here costs) |
| Technical names | `Backlog`, `Up Next`, `In Progress`, `Blocked`, `Done`, `Priority`, `High`, `GitHub`, `KanbanFlow`, milestone titles, `#N`, file paths, function names, label names, field names | ASD-STE100 permits technical names; the controlled vocabulary applies to the connecting prose |
| Script output | `sweep.py`, `dependency-graph.py`, `stage.py`, `next-session-prompt`, `ties` blocks | Already voice-OFF today; the knob governs dialogue only |
| Board-write drafts | Session-note drafts, issue-body drafts, close-comment drafts, body-edit diffs | Board writes are plain technical prose under every value of the knob |

The section headers of a stub's template are technical names for this purpose. "Shape:",
"Milestones:", "In flight" and their peers pass through.

### 5.4 Names for the conditions the project calls "drift"

STE has no approved word "drift", and the project uses the word for at least five
conditions. Under `ste` each condition gets its own phrase. The table is the mapping; the
project's own term stays in section headers because those are technical names.

| Project term | Condition | `ste` phrase |
|---|---|---|
| Metadata drift | A board field does not match the item's state | "the board record does not match the item" |
| Plan/spec drift | A plan or spec file does not match its issue | "the plan does not match the issue" |
| Doc-to-code drift | A document claims behavior the code does not have | "the document does not match the code" |
| Drift-reconcile | Work starts with no issue to track it | "no issue tracks this work" |
| Drift since filing | An issue body cites a path or symbol that no longer exists | "the issue body is not correct: `<path>` does not exist" |

### 5.5 Selection and fail-safe

The bullet has exactly three literal values. `- voice: ste` selects the mode. `- voice:
disabled` selects plain prose. `- voice: enabled`, an absent bullet, a typo, or any other
value selects the character voice. This extends the existing fail-safe rule in `SKILL.md` §
"Project-level kill switch" from one literal to two. The two modes cannot conflict: one
bullet holds one value.

## 6. Surface inventory — every file that changes

| File | Change |
|---|---|
| `skills/jared/references/voice-ste.md` | New. The rules (§ 5.1), the aside rule, the passthrough table, the drift-name table, four paired examples, the diagnostic checklist, the fixture pointer. |
| `skills/jared/references/voice.md` | Kill-switch paragraph names `ste` and points at the new file. F58: boundary row 16 names the general "no issue tracks this work" trigger, not `/jared-groom`. F59: row 24 adds `capture-context.py`. |
| `skills/jared/SKILL.md` | § "Project-level kill switch" names the three values and the fail-safe rule for two literals. § "Reference pointers" lists `voice-ste.md`. |
| `commands/jared.md` | Line 5 `ste` branch. Lines 26, 45, 49: aside and warm-line instructions carry the void sentence. |
| `commands/jared-start.md` | Line 5 `ste` branch. Lines 144–146, 160: opening line and aside carry the void sentence. Step 7 heading phrases get STE alternatives ("Last Session note", "Acceptance criteria"). |
| `commands/jared-wrap.md` | Line 5 `ste` branch. Line 42: framing and aside carry the void sentence. Line 177 closing line. |
| `commands/jared-groom.md` | Line 5 `ste` branch. Lines 26–28, 76: warm framing and the clean-sweep quote carry the void sentence. |
| `commands/jared-reshape.md` | Line 5 `ste` branch. Lines 33, 58: the aside slot and the stakes line carry the void sentence. The proposal template's section skeleton is kept per § 3b. |
| `commands/jared-audit.md` | Line 5 `ste` branch. Lines 69, 79: warm framing and the verdict-framing quote carry the void sentence. |
| `commands/jared-stage.md` | Line 5 `ste` branch. Lines 22, 28, 75: warm intro and closing carry the void sentence. |
| `commands/jared-init.md` | Line 5 `ste` branch. Lines 16–23: the self-introduction and its aside carry the void sentence; an STE introduction replaces them under `ste`. |
| `commands/jared-file.md` | Line 5 `ste` branch. Lines 76–82: warm report and gentle failure line carry the void sentence. |
| `skills/jared/references/parallel-sessions.md` | Line 214: the pointer names both files, keyed on the bullet. |
| `docs/project-board.md` | § Jared config: the `voice:` bullet lists three values with one line each. |
| `skills/jared/assets/project-board.md.template` | Same bullet text as above. |
| `skills/jared/scripts/bootstrap-project.py` | The KanbanFlow full-doc template (line 860) emits a bare `- voice: enabled`. It gains the same one-line-per-value description the asset template carries. The GitHub full-doc template emits no `## Jared config` section today; this design does not add one. |

`lib/board.py`, `tests/`, `sweep.py`, `dependency-graph.py`, `stage.py`: no change.

## 7. The `ste` branch sentence — one shape for every stub

Every stub's line 5 today ends with the kill-switch sentence for `disabled`. The `ste` branch
is added as a second sentence in the same paragraph, in the same shape, so a reader who
knows one stub knows all nine:

> **STE mode:** if the same section contains `- voice: ste`, render in ASD-STE100 Simplified
> Technical English per `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice-ste.md` — keep the
> structural content and the section skeleton, pass machine strings and technical names
> through verbatim, and treat every aside or warm-framing instruction in this file as void.

The per-instruction void sentence, placed next to each aside slot, is one shape too:

> *(Under `- voice: ste` this line is void: render one statement of fact instead.)*

## 8. Verification

There is no test to add; the change is prose. Verification is by execution:

1. Set `- voice: ste` on this board's `docs/project-board.md` in the feature branch.
2. Run `/jared` and `/jared-groom` (a short surface and a long one).
3. Check each output against the diagnostic checklist in `voice-ste.md`: no aside; no `-ing`
   verb form; no sentence over 25 words in description or 20 in procedure; every
   `degraded:` string, column name, `#N` and path unchanged; the section skeleton intact.
4. Save both outputs to Joplin as the fixture named in § 4.
5. `pytest`, `ruff check .`, `ruff format --check .`, `mypy` pass unchanged (they exercise no
   file this design touches, which is the point).

The bullet stays set on this board when the PR merges. The operator's stated default is
`ste`, and this board is the first bake site for the mode.

## 9. Non-goals

- `ste` does not change board writes. Issue bodies, Session notes and commit messages are
  plain technical prose under every value of the knob. An "STE in board writes" mode would be
  a separate decision on the lane rule, not on this knob.
- `ste` does not change script output. `sweep.py` and its peers print what they print.
- No conformance checker. A Python STE linter would be a parser on a doctrine value.
- No `voice:` matrix. `ste` and `disabled` are values of one bullet, not two bullets.

## 10. Implementation phases (for the plan)

1. `references/voice-ste.md` — the spec file, complete.
2. Config surfaces — `docs/project-board.md`, the template, `bootstrap-project.py`.
3. The nine stubs — line-5 branch plus per-instruction void sentences.
4. `SKILL.md` and `voice.md` pointers; F58 and F59 as a separate commit.
5. Verification runs, Joplin fixture note, CHANGELOG entry.
6. PR.
