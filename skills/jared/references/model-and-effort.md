# Model and reasoning effort — the `/jared-start` recommendation

This reference is loaded on demand by `commands/jared-start.md` step 7. It defines the
recommendation Jared prints in the announce: which model to run the session's work with,
and at what reasoning effort.

**Posture: advisory, exactly as the ties block is advisory.** The block never gates the
start. The operator may take it, change it, or ignore it. Jared prints it and moves on.

## Why the announce is the place

The announce is the last thing the operator reads before work begins. It is the only
moment in the flow where the session's scope is known (the body is loaded, the criteria
are counted, the ties are back) and no file has been touched yet. A recommendation
delivered after the first edit is a recommendation delivered too late — the context is
already spent on the wrong setting.

## Two axes, not one

Model and effort answer different questions. Collapsing them into one "how big is this"
dial is the obvious design and it is wrong: it cannot express the two cases that matter
most.

| Axis | Question it answers | Driven by |
|---|---|---|
| **Model** | How much must be held at once, and how expensive is a wrong turn to unwind? | Breadth and stakes — file count, surface durability, blast radius |
| **Effort** | How much reasoning does each individual step need? | Depth — unsettled questions, subtle invariants, known landmines |

The two cases that a single dial cannot express:

- **Small but subtle.** A three-line change to the auto-close guard regex. One file, one
  criterion — but getting it wrong silently closes issues. **Fast** tier, **high** effort.
- **Large but mechanical.** Renaming a provider method across 40 call sites with the
  shape already fixed. Many files, no judgment. **Deep** tier, **low** effort.

## Signals — all already in hand at step 7

The recommendation is derived from data steps 1–6 already fetched. It adds no API call.

| Signal | Where it comes from | Reads as |
|---|---|---|
| `Priority` | `jared get-item <N>` | Stakes |
| Acceptance-criteria count | bullets under `## Acceptance criteria` in the body | Breadth |
| Code paths cited in the body | backticked paths, function names, line references | Breadth, and whether the shape is already fixed |
| `## Planning` | the body — a path, or `(none)` | A linked spec with phases means breadth |
| `## Depends on` | the body | A non-empty list means the work sits in a chain |
| An unsettled question | a body heading that asks one, or the words "decide", "settle", "choose between" | Depth |
| Ties | `jared ties <N>` stdout plus the semantic scan | Breadth — a `strong` tie means a second issue's surface is in play |
| Title prefix | the posture block — e.g. `[kanbanflow]` | Which subsystem, hence which landmines |

**Labels are not a reliable signal here.** `jared get-item` does not emit them and no
prescribed step fetches them, so treat a label as reinforcing evidence when it happens to
be visible and never as a required input. A rubric that depends on a field the flow does
not fetch is a rubric that silently degrades to its default.

## The rule — floors, highest match wins

Do not score points. Match triggers; the highest tier any trigger raises you to is the
recommendation. This is the same posture as a `jared ties` confidence tag: legible by eye,
consistent between sessions, no false arithmetic rigor.

### Model floor

Tiers are named by **role**, not by model name. Model names change; the roles do not. The
authority for which models a given install actually offers is that install's `/model`
list — this table names examples current as of 2026-09 and does not rank them.

| Tier | Example (2026-09) | Raise to this tier when any of these is true |
|---|---|---|
| **Deep** | Opus 5 | The body carries an unsettled design question. The change alters a rule, template, or contract on a doctrine surface — `SKILL.md`, a slash-command stub, a `references/` doc, `CLAUDE.md`. The change crosses the provider seam or any public contract. `Priority: High` together with five or more acceptance criteria. A linked spec with numbered phases. |
| **Default** | Sonnet 5 | Anything with acceptance criteria and a code change. This is the floor for ordinary work and the answer most sessions get. |
| **Fast** | Haiku 4.5 | Two or fewer criteria, one file, no cited code paths beyond the one being edited, and no open question. A typo, a link, a version bump, a changelog line. |

**The doctrine trigger is about rules, not bytes.** A doctrine file is a doctrine file, but
correcting a typo, a dead link, or a stale path *inside* one changes no rule and does not
raise the floor. Ask what a future session would do differently because of the edit. If
the answer is "nothing", it is a Fast-tier correction that happens to live in
`references/`.

### Effort floor

The levels are Claude Code's own: `low`, `medium`, `high`, `xhigh`, `max`. Which levels an
install offers depends on the model. Use these names verbatim — they are the argument the
operator passes to `/effort`.

| Level | Raise to this level when any of these is true |
|---|---|
| **xhigh** | Both axes are loaded at once: an unsettled design question *and* a doctrine surface or public contract. The session has to decide something before it can build it. |
| **high** | The issue asks for something to be *settled and recorded*. The work touches a known landmine (see below). A tie came back `strong`. The change alters a rule that other sessions will follow without re-deriving it. |
| **medium** | The default. A known shape, ordinary care. |
| **low** | The edit is fully specified by the issue body and needs transcription, not judgment. |

**`max` is operator escalation, never a recommendation.** Jared does not trigger on it. It
is the level an operator reaches for after `xhigh` has already been tried and was not
enough, and that is a judgment from inside the work rather than from the announce.

### Known landmines — read the consuming project's `CLAUDE.md`

This reference ships with the plugin and loads on every project Jared runs against, so it
cannot carry a fixed list. **The landmine source is the consuming project's own
`CLAUDE.md`** — the section where a project records the traps that have already produced a
wrong conclusion. When the session's work touches one, raise effort to **high**.

Jared's own repo is the worked example, not the list to apply elsewhere. Its `CLAUDE.md`
records, among others:

- The auto-close guard pattern. Fired three times, always from text that was *explaining*
  the danger.
- The dual import path for `Board` — `lib.board` and `skills.jared.scripts.lib.board` are
  two module objects, so a patch on one is not a patch on the other.
- Capability gate versus backend selector. `board.backend != "github"` picks a data
  source; a `Capability` answers whether a concept is expressible.
- Doctrine versus parsed field — the #114 precedent, where a parsed field with a passing
  test shipped and was reverted because nothing read it.

A project whose `CLAUDE.md` records no such section simply has no landmine trigger. The
other effort triggers still apply.

## Worked contrast pair

The two ends of the rubric, each dry-run through the tables above rather than asserted.

**A one-line changelog correction** — fix a wrong PR number in a `CHANGELOG.md` entry.

Dry run: one criterion, one file, no cited code paths, no open question, no ties, and no
rule changes. No Deep trigger matches. No Default trigger matches — there is no code
change. The Fast row matches on every clause. No effort trigger matches; nothing is to be
settled and recorded, and the body specifies the exact edit.

```
Suggested settings for this session:
  model:  Haiku 4.5 — one file, one criterion, and no rule changes.
  effort: low — the issue body specifies the exact edit.  (current: xhigh)
  Apply with: /model haiku · /effort low
```

**This issue, #430** — add the recommendation block to a slash-command stub.

Dry run: the Deep row matches twice — the body carries an unsettled question about what
Claude Code can control, and the change alters a rule on a doctrine surface
(`commands/jared-start.md` plus a new `references/` doc). Six acceptance criteria. The
xhigh row matches: acceptance criterion 3 asks for an unsettled control question to be
"settled, and recorded in the issue", and the surface it changes is doctrine. Both axes
are loaded at once, which is exactly what separates xhigh from high here.

```
Suggested settings for this session:
  model:  Opus 5 — doctrine surface, and the control question is unsettled.
  effort: xhigh — an unsettled control question on a doctrine surface.  (current: xhigh — already set)
  Apply with: /model opus
```

The two differ on both axes, and each reason cites this issue rather than restating the
tier.

## The control question — settled 2026-09-19

**Jared cannot set the model. It recommends, and the operator applies.** This was the
open question in #430 and it is closed. Verified against Claude Code v2.1.278 and the
current `slash-commands.md`, `hooks.md`, `settings.md` and `model-config.md`.

**`model:` frontmatter on a command stub is per-turn.** The docs state the override
"applies for the rest of the current turn and isn't saved to settings. The session model
resumes when you send your next prompt." The turn is the whole agentic loop, so it covers
`/jared-start` reading the issue and printing the announce — and it ends exactly at
handback, which is where the implementation work starts. It would change the model that
prints the plan and not the model that writes the code. That is the opposite of what #430
wants.

**An `effort:` frontmatter key also exists** (`low`, `medium`, `high`, `xhigh`, `max`)
and is likewise skill-scoped. Its row does not state reversion the way the `model:` row
does, so same-turn scope is *inferred* by parallel construction rather than quoted —
record it that way and do not assert it as documented. It is unusable here regardless,
for the reason below, which does not depend on scope at all.

**A second reason frontmatter is the wrong shape, independent of scope:** frontmatter is a
static string and this recommendation is computed per issue. Even with session scope, one
pinned value could not express "Haiku for the changelog fix, Opus for the refactor."

**No other channel reaches it either.** `PreModelSwitch` can block a switch but not start
one. `PostModelSwitch` only observes. No hook output schema carries a model field. Writing
`model` or `effortLevel` to `settings.json` is read once at session start, so it lands at
next launch, not now. `ANTHROPIC_MODEL` and `--model` are launch-time only. The one live
switch is a human typing `/model` or `/effort`.

**So the deliverable is the recommendation plus the exact commands to run** — which the
issue anticipated as "still most of the value".

**If the goal is really "run the work on a stronger model", the supported mechanism is
delegation, not session switching:** dispatch a subagent with an explicit `model`. That is
a different tool for a different job and it is out of scope here, but it is the thing that
actually works, so the announce should not imply otherwise.

## How the operator applies it

Two commands, named exactly, because a recommendation the operator has to go look up is a
recommendation that gets skipped:

- `/model <name>` — switches the live session.
- `/effort <level>` — switches the live session. `/effort status` prints the current level.

**Effort is readable at runtime; the model is not.** This asymmetry is documented and was
verified in-session on 2026-09-19.

- `$CLAUDE_EFFORT` is exported to the Bash tool, and `${CLAUDE_EFFORT}` substitutes in
  command content. A live `echo "$CLAUDE_EFFORT"` returned `xhigh`.
- There is no `$CLAUDE_MODEL`. `hooks.md` says so in as many words, and no substitution
  variable carries it. `ANTHROPIC_MODEL` is unset unless the operator exported it, and it
  does not track `/model` switches anyway.

So the effort line compares against the live value and the model line cannot. Say only
what is known: name the current effort level, and do not claim to know the current model.

**Do not build a hook relay to read the model.** It is possible — a bundled `SessionStart`
plus `PostModelSwitch` pair writing a session-keyed side file — and it is not worth it. It
adds two hooks, a temp file and a failure mode to a line whose whole job is advisory.
An unconditional model line costs nothing and is honest about what it knows.

**`ultrathink` is not an effort control.** The keyword adds an in-context instruction and
the effort level sent to the API is unchanged. "think hard" and similar phrases are passed
through as ordinary prompt text and do nothing. Never recommend a keyword in place of
`/effort`.

## Sibling convention — subagent defaults

A user's `CLAUDE.md` may already set subagent model defaults (for example,
implementation → Sonnet, review → Opus). That convention governs agents Jared
*dispatches*. This rubric governs the model the *session itself* runs on. They agree on
direction and they are not the same setting — do not let one overwrite the other, and
prefer the project's own `CLAUDE.md` when it speaks to the question directly.

## Rendering

The block goes in the step-7 announce, between the session plan and the git line. Each
reason is one line tied to *this* issue — never a generic restatement of the tier.

```
Suggested settings for this session:
  model:  <name> — <one-line reason from this issue>
  effort: <level> — <one-line reason from this issue>  (current: <$CLAUDE_EFFORT>)
  Apply with: /model <name> · /effort <level>
```

**The `current:` note is only on the effort line**, because only effort is readable. Read
it with `echo "$CLAUDE_EFFORT"` in the same batch as the other step-7 reads. When the live
level already equals the recommendation, say so and drop the `Apply with:` effort half —
telling an operator to set what is already set trains them to ignore the block. If the
variable is empty, omit the `current:` note rather than guessing.

**Never print a `current:` note for the model.** It is not knowable, and a guessed one is
worse than none.

**Name the model the way that install's `/model` lists it.** Two identifier vocabularies
are in circulation — short aliases (`sonnet`) and full ids (`claude-opus-5`) — and both
appear in a real `settings.json`. The `/model` list is the authority. Do not invent a
third form: a recommendation that sends the operator to an error is worse than none,
which is the whole reason the block names the command at all.

**Available effort levels depend on the model.** If the level you would recommend is not
offered by the model you are recommending, name the highest level that model does offer
rather than a level the operator cannot select.

Under `- voice: enabled` and `- voice: disabled` the heading is
`Suggested settings for this session:`. Under `- voice: ste` it is
`Recommended settings:` — "suggest" is not an approved word and `propose` maps to
`recommend`. The reasons become STE sentences: one clause, active voice, no aside. Model
names, level names, `/model`, `/effort` and every other machine string pass through
verbatim under all three values, per `references/voice-ste.md` § "Passthrough".

## Suppression

An operator who always runs one model does not want the line every session. The knob is
`- model-advice: off` in `docs/project-board.md` § `## Jared config`. Values: `on`
(default) and `off`.

**The bullet is doctrine-only.** No Python parses it. `commands/jared-start.md` reads the
bullet from the doc the same way it reads `voice:`, and when the value is `off` it omits
the block. This is deliberate and it is the #114 rule applied, not evaded: the mistake in
#114 was parsing a field in `lib/board.py` that no CLI surface gated on. A bullet read by
a prose surface has a reader. Adding a `Board.model_advice` attribute would not.
