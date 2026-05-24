# Changelog

One-line summaries for every shipped tag of the `jared` plugin. Newest at the top.
Per-release deep dives live on the corresponding [GitHub Release](https://github.com/brockamer/jared/releases) where available — the v0.13.0+ era is consistently released; earlier tags and a few in the v0.14.0–v0.18.1 window predate the release-creation discipline (pinned in v0.20.0 / #175).

Format: each entry starts with `## v<x.y.z> — YYYY-MM-DD`, followed by terse bullets grouped under **Features** / **Bug fixes** / **Refactor** / **Doctrine** / **Performance** / **Patch** when more than one item shipped. Items end with the PR number or issue number that landed them; GitHub auto-links both.

Convention is documented in [CLAUDE.md](CLAUDE.md) § Versioning. Pre-`v0.2.0` history is omitted — `v0.2.0` is the level-up release that established the current Jared shape.

## v0.23.1 — 2026-05-24

**Bug fixes**
- `jared file --milestone NAME` failed with HTTP 422 (`"title" wasn't supplied`) since v0.23.0 — the open-milestones fetch passed `-f state=open -f per_page=100` to `gh api`, which sends those as a POST body and hits the create-milestone endpoint instead of listing. Filters moved to the URL query string. Argv-shape regression test added (the previous tests routed by substring match on `"milestones"` and returned a synthetic list, green-lighting the malformed call). (#256, closes #254)

## v0.23.0 — 2026-05-23

**Features**
- Multi-session discipline — solo sessions still write a presence lock at `<repo>/.jared/session-<pid>.lock` so siblings can detect them; `/jared-start <issue> --session N` opts into worktree isolation (creates `~/Code/<repo>-<issue>/`, fresh `feature/<issue>-<slug>` branch off `origin/main`, CWD shifts). `/jared-start <issue> --no-worktree` explicitly acknowledges shared-`.git/HEAD` risk. `/jared-wrap` clears the lock; stale locks are caught by the next session's PID-liveness check. (#247, #250, closes #231, #235, #236)
- Per-session WIP arithmetic — `jared summary` now collapses In Progress items sharing a `session-N` label into one workstream count; the WIP cap compares against workstreams, not items. (#250, Phase 1.1)
- `jared file` requires `--milestone NAME` or `--no-milestone` — stops the orphan-issue stream that motivated the findajob 2026-04-24 incident. Breaking CLI contract; no auto-default. (#239, closes #238)
- Default WIP caps raised to **8 Up Next / 4 In Progress** (was 5/3). (#245)
- MCP-token-scope mentioned in the token-scope diagnostic to disambiguate `gh`-CLI from MCP-plugin auth. (#213, closes #210)

**Bug fixes**
- Native blocked-by edges in ties detection now tagged `[blocker]`, not `[cross-ref]` — fixes mislabeling on edges created via `jared blocked-by`. (#249, closes #230)
- `/jared-start` default-cap doctrine drift — stub said 3, canonical is 4. (#250, Phase 1.3)
- Sweep counter + closed-cache filter use Status, not `content.state` — restores correct counts after the Status-column migration. (#224, closes #189)
- `/jared-stage` bullet-style error message restates the `<details>` wrapper requirement so the fix is in the error itself. (#225, closes #195)
- Plan `## Issue` section list items accept bold-wrapped refs (`- **#123** ...`). (#214, closes #204)

**Performance**
- `capture-context.py` + `archive-plan.py` body reads migrated to REST (was graphql) — drops the graphql-pressure cost of these batch operations. (#212, closes #208)

**Doctrine**
- GitHub API mechanism selection — four-mechanism routing policy in `operations.md` + `SKILL.md`. (#211, closes #207, #209)
- CHANGELOG.md backfilled with all 25 shipped tags; convention pinned. (#221, closes #165)
- `file://` install dev-artifact leakage documented with cleanup recipe. (#219, closes #198)
- Stale `GH_TOKEN` env-var confusion called out in README prereqs. (#246, closes #138)
- Memory→doctrine consolidation + `parallel-sessions.md` reference + session-N semantics + pre-parallel ritual + WIP arithmetic doc. (#244, #250 Phase 1.2)
- Multi-session stage/start/git hygiene design spec recorded. (#234, closes #232)
- `## Jared config` section backfilled into jared/jared's own project-board doc. (#222, closes #203)

## v0.22.1 — 2026-05-22

**Doctrine**
- GitHub API tool selection — investigation + routing policy across four mechanisms (`gh` subcommands, raw REST, graphql, MCP plugin); capability matrix, rate-limit cost attribution, auth deconfliction, per-operation routing recommendation. MCP plugin has no ProjectV2 tools; graphql pressure source is `gh project item-list` at ~10 pts/item; conversational layer has separate doctrine from the CLI. (#205, investigates #202)

## v0.22.0 — 2026-05-22

**Features**
- Activate the Jared character voice in every slash-command stub (`/jared`, `/jared-start`, `/jared-wrap`, `/jared-groom`, `/jared-stage`, `/jared-init`, `/jared-audit`, `/jared-reshape`, `/jared-file`). Each stub now opens with a `**Voice.**` block naming the contract + kill switch; user-facing output templates rewritten in voice. (#199, #200)
- Project-level voice kill switch: `- voice: disabled` in `docs/project-board.md` § `## Jared config`. Mirrors `model-guidance` shape; default ON. (#199, #200)
- Jargon translation pass: "pullable" → "ready when checked", "WIP cap" → "how many things going at once", "blocked" → "waiting on something else", "acceptance criteria" → "what we need to be true to call this done". (#199, #200)

**Doctrine**
- Voice activation lives entirely in the plugin — no user-local settings, hooks, memory entries, or CLAUDE.md tweaks required. (#199, #200)
- CLI-string OFF policy surfaced explicitly in `SKILL.md`: CLI error messages and batch-script diagnostics (`sweep.py`, `bootstrap-project.py`, `archive-plan.py`, `capture-context.py`) stay voice-OFF for greppability. (#199, #200)

## v0.21.0 — 2026-05-22

**Performance**
- `jared summary` and `jared next-session-prompt` no longer pull Done items; graphql cost is bounded by open issue count instead of total board size. On a 380-Done/20-open board, cold-cache `summary` runs in ~6s. New `Board.open_items()` uses one batched `repository.issues(states: OPEN)` round-trip. (#185, #187)

**Bug fixes**
- Defensive truncation guard on every `gh`-list call that hits a `--limit` cap (`Board.board_items()`, `sweep.fetch_items()`, `_fetch_recently_closed()`) — raises `GhInvocationError` when result count equals the cap (silently-wrong before). (#185)

**Refactor**
- Stuck-closed detection migrates from "scan in-memory CLOSED" to a 14-day REST lookback + batched projectItems probe. Drift older than the window stays sweep's job.

## v0.20.0 — 2026-05-21

**Features**
- `/jared-audit` — skeptical kanban-manager action that walks the backlog oldest-first, runs a seven-question per-item checklist, produces operator-approved verdicts (`close-as-completed` / `close-as-not-planned` / `reshape` / `leave-alone`). Velocity-aware staleness threshold `2 × median_age_at_close` clamped to [14, 60] days; proposed milestone dates anchor to recent PR-merge cadence. Opt-in `advisor()` pass for non-trivial batches. (#169, #182)
- `jared groom` — project-configurable **doc-sync gate**: when a closed PR touched the configured code surface but didn't touch a configured operator doc, the sweep emits a soft advisory line. Config in `docs/project-board.md` § `### Current-state operator docs`. (#163, #180)

**Bug fixes**
- `compute_velocity` switched to correct `gh` CLI invocations (`gh issue list --state closed --search "closed:>=DATE"` and `gh pr list --state merged --search "merged:>=DATE"`). (#181, fixed within #182)

**Doctrine**
- Getting-started walkthrough — first 15 minutes for a new user, validated against the live testbed. (#164, #179)
- Release discipline pinned: every `git push origin v*` must be paired with `gh release create`. (#175)

## v0.19.0 — 2026-05-20

**Refactor**
- `## Model & execution guidance` section refactored from imperative dispatch directives ("USE a Haiku subagent") to classification + decision-point prescription. Grounded in a 47-audit retrospective (#162): task-tier prescriptions held 23–43% worked-rate while `advisor()` decision-point prescriptions held 95%. Phase 1 dropped Cheap/Standard `(USE a … subagent)` parentheticals across 5 surfaces. Phase 2 flipped the wrap-time guidance audit from compliance-eval to judgment-eval. (#172, #173)

**Bug fixes**
- Bootstrap project-board template re-synced: epic-row + scope-labels paragraph restored. (#170, #171)
- Bootstrap template no longer lists `blocked` as a default label (contradicted Jared's invariant); invariant pinned with a test. (#159, #168)

## v0.18.1 — 2026-05-16

**Patch**
- Accurate not-pullable reason in `/jared-stage` when the acceptance section has no `-`-prefixed bullets — covers numbered-list, prose, and `- Criterion N` placeholder cases. (#160)

## v0.18.0 — 2026-05-16

**Features**
- Epic-label-aware Deferred filtering in `/jared-stage`. (#146)
- Milestone display/sort fix in stage rendering. (#145)

**Performance**
- `fetch_milestone_map` perf cleanup — milestone is top-level on raw items. (#153)
- ETag / conditional GET on issue-state checks. (#147)

**Doctrine**
- Projects v2 workflow recommendations + commit-body keyword hygiene docs (preventing post-close Status reversion). (#156)
- CLAUDE.md version-drift fix in release docs. (#150)

## v0.17.0 — 2026-05-16

**Performance**
- Cross-process snapshot cache for `gh project item-list`. (#52)
- Phase 2.a REST migration for per-issue state checks. (#54)

**Features**
- New `--fresh` flag on `jared summary` and `jared next-session-prompt`. (#52)

**Bug fixes**
- `jared close` defense-in-depth — Status reliably moves to Done on direct issue closure. (#137)

**Doctrine**
- README fresh-eyes pass against the marketplace install flow (no implicit CLAUDE.md assumptions). (#139)
- CLAUDE.md slash-command inventory adds `/jared-stage`. (#142)

## v0.16.0 — 2026-05-16

**Features**
- Split `deferred_reason` by failure mode in `/jared-stage`. (#131)

**Bug fixes**
- `_ACCEPTANCE_SECTION` accepts `<details>` without literal `<summary>Expand</summary>`. (#134)
- `_BLOCKED_BY_SECTION` regex terminates on H3 lookahead. (#130)

## v0.15.0 — 2026-05-14

**Features**
- `/jared-stage` — continuous staging discipline (Backlog → Up Next promotions, Blocked revisits). (#128)

## v0.14.0 — 2026-05-14

**Features**
- Imperative model guidance + wrap-time retrospective audit on `## Model & execution guidance` sections. (#126)

## v0.13.0 — 2026-05-08

**Features**
- `Board` autodiscovers the convention doc across canonical paths (`docs/project-board.md`, `docs/maintainers/project-board.md`, `PROJECT_BOARD.md`, `.github/project-board.md`). New `Board.find_default_path()` and `Board.from_default()` classmethods. (#117)
- `/jared-wrap` no longer writes `tmp/next-session-prompt-<TIMESTAMP>.md` files; handoff posture assembled on-demand at `/jared-start` time from current board state via `jared next-session-prompt`. (#121)

**Bug fixes**
- `fetch_blocked_by_edges` dead fallback to non-existent `issueDependencies` field removed. (#118)

**Doctrine**
- `/jared-start` scans for semantic ties (`possibly-already-done` and `semantic-overlap`) in the conversational layer; `Confidence` literal grew an `"llm"` variant. (#80)

## v0.12.0 — 2026-05-08

**Performance**
- `find_item_id` uses a scoped `projectItems` query (~1–3 pts vs ~200–300 pts on full board scan). Bulk-routing 30 issues now ~30–90 pts vs ~9,000 pts. (#109)
- `sweep.py` / `Board.fetch_items()` `--limit` raised 200/500 → 2000. (#113)

**Bug fixes**
- `_add_to_board` retries `gh project item-add` once on missing-`id` response (intermittent GitHub API). (#112)
- `--priority` accepts any case + `med` alias for `Medium`. (#116)

## v0.11.0 — 2026-05-05

**Features**
- New `## Model & execution guidance` section on every new issue body, classifying work into Cheap / Standard / Smart tiers + subagent dispatch hints + execution sketch. Enforced at file-time (`/jared-file`) and start-time (`/jared-start` backstop). Project-level kill switch `- model-guidance: disabled` in `## Jared config`. (#114, #115)

## v0.10.0 — 2026-05-03

**Doctrine**
- Full Jared Dunn voice contract for user-facing dialogue, with on/off boundary. Voice ON in dialogue (`/jared`, `/jared-start`, `/jared-wrap`, drift-reconcile prompts, error-mode chatter); voice OFF in board writes (issue bodies, Session notes, PR descriptions, commits, source code, tests). New `skills/jared/references/voice.md`. (#104, #108)

## v0.9.0 — 2026-05-03

**Features**
- Shipped-section archival on `/jared-wrap`. (#89)

**Refactor**
- Shared issue-ref parser extracted across surfaces. (#86)

**Bug fixes**
- `sweep` status-null check. (#85)

## v0.8.1 — 2026-05-02

**Performance**
- `_cmd_ties` switched to a single batched fetch. (#81)

## v0.8.0 — 2026-05-01

**Features**
- `jared add-to-board <N>` — atomicity recovery for orphaned issues (carved from the trailscribe incident). (#64)
- Verify `gh project item-add` idempotency. (#71)
- Archive older handoff prompts in `tmp/` after writing a new one. (#69)

**Bug fixes**
- Scrub `GH_TOKEN` / `GITHUB_TOKEN` from `gh` subprocess env (token shadowed OAuth scope). (#65)
- Token-scope diagnostic on project-mutation 403s. (#66)

## v0.7.0 — 2026-05-01

**Performance**
- Graphql rate-limit relief — measurement + cache discipline pass. (#49, #51)

**Bug fixes**
- `jared summary` stuck-closed detection. (#43)
- Plan/spec drift regex tightened. (#48)

**Features**
- Session-note `## Session N+1` shape adopted. (#55)

**Refactor**
- Repo-wide `ruff format` pass. (#56)

## v0.6.0 — 2026-04-26

**Features**
- `/jared-start` picks up the most recent `tmp/next-session-prompt-*.md` handoff prompt; surfaces a Handoff posture block above the per-issue announcement. Drift-checks parsed `## To start` target via `jared get-item`. (#44, #45)

## v0.5.0 — 2026-04-25

**Refactor**
- `mypy --strict` on `skills/jared/scripts/` reports 0 errors (down from 51 across `sweep.py`, `bootstrap-project.py`, `dependency-graph.py`). Phase-numbered commits by error code: 4 `[arg-type]`, 10 `[no-any-return]`, 37 `[type-arg]`. (#33, #41)

**Doctrine**
- CLAUDE.md "Phase 3" / ruff-excluded language retired — batch scripts now pass lint + type-check alongside the rest of the tree. (#33)

**Bug fixes**
- `archive-plan.py` recognizer for `**Issue:**` bold-line spec/plan format. (#37, #39)
- `next-session-prompt.md.template` Frame orientation note + `jared-wrap.md` step-7 trim. (#40)
- `pyproject.toml` version re-synced with `.claude-plugin/plugin.json` (drift since PR #35). (#42)

## v0.4.0 — 2026-04-25

**Features**
- Optional session handoff prompt for `/jared-wrap`. New `jared next-session-prompt` CLI subcommand for the board-derived skeleton. (#35, #36)

**Bug fixes**
- `/jared-start` WIP command typo. (#32)
- `jared-init` bootstrap defaults. (#31)

## v0.3.1 — 2026-04-24

**Bug fixes**
- `jared close` rate-limit handling. (#27)
- `jared comment` JSON parse on multi-line bodies. (#26)

**Features**
- `/jared-init` links to the upstream repo. (#28)

## v0.3.0 — 2026-04-23

**Bug fixes**
- `archive-plan.py` PR-detection covers merged PRs without explicit `closes` keyword. (#3)
- `jared file` doesn't fall back to a full `item-list` scan when project-items query returns. (#21)
- Closed-not-done `propose` fix. (#20)
- `jared` traceback leak on subprocess errors. (#11)
- Legacy board parser tolerance. (#14)
- `jared file` verify-and-retry on transient failures. (#15)

**Features**
- Bootstrap self-board flow. (#6)
- `/jared-init` legacy-pattern migration. (#17)

**Refactor**
- Unified error-prefix across CLI surfaces. (#16)

**Doctrine**
- README polish + social image. (#7, #19)

## v0.2.0 — 2026-04-22

**Features**
- Level-up release — initial Jared shape (skill + slash-commands + Python CLI stewarding a GitHub Projects v2 board). Implements spec `docs/superpowers/2026-04-22-jared-levelup-design.md`. (#2)
