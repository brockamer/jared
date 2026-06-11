# Phase 1 — Read-Only Review Fan-Out (Workflow Blueprint)

> **Execution:** this plan runs as a single **Workflow** (the `Workflow` tool), not subagent-driven TDD. It produces *findings appended to the ledger*, not code. Phase 3 fixes them.

## Issue
#350 — Phase 1 (read-only review fan-out) of epic #348.

**Spec:** `docs/superpowers/specs/2026-06-10-marketplace-readiness-review-design.md` § Phase 1
**Ledger:** `docs/superpowers/reviews/2026-06-10-marketplace-readiness-ledger.md`

**Goal:** Across six review dimensions, fan out finder agents over the full plugin surface, adversarially verify every finding, dedup, and append confirmed findings (P0/P1/P2 + evidence + suggested fix) to the ledger — so Phase 3 has a complete, trustworthy work-list.

**Architecture:** deterministic cheap checks first (scripted, feed the finders) → parallel finder fan-out (one agent per surface cluster, structured output) → per-finding adversarial verify (skeptics prompted to *refute*; perspective-diverse for correctness/security) → dedup + severity-normalize in JS → merge survivors into the ledger. Pipeline where possible so a dimension's findings verify while other dimensions still review.

**Model:** finders + verifiers use **opus** (review task, per user default). Deterministic checks are bash, no model.

---

## Stage 0 — Deterministic pre-checks (scripted, no agents)

Run before the fan-out; results are passed into the relevant finders as ground truth and logged directly as findings where unambiguous.

- [ ] **Backtick-path existence sweep.** Extract every `` `path` `` token from all docs (`*.md`, `SKILL.md`, command stubs, references, assets) and assert each path that looks like a repo file exists. Misses → candidate F-findings (dim 1c). *(Lesson: code-symbol verification has a blind spot for prose paths.)*
- [ ] **Hardcoded-path grep.** `grep -rn` for `~/.claude`, `/home/brockamer`, absolute `~/.secrets`, and bare `~/Code` in shipped surfaces (commands/, skills/, docs/ excluding this review's own notes). Each hit in a stranger-facing surface → dim 1d/1f finding.
- [ ] **`${CLAUDE_PLUGIN_ROOT}` discipline.** Confirm script invocations in command stubs use `${CLAUDE_PLUGIN_ROOT}` not hardcoded plugin-cache paths.
- [ ] **Metadata schema validate.** `plugin.json` + `marketplace.json` parse as JSON; required keys present; `version` parity with `pyproject.toml`; `marketplace.json` matches the documented schema URL.
- [ ] **Full-history secret scan.** `gitleaks detect` if available, else `git log -p | grep -nE '<token-patterns>'` (ghp_, github_pat_, KanbanFlow 26-char, generic `API_TOKEN=`) across all history. Any hit → **P0** (rotate, not just rm).
- [ ] **`gh`-fallback import probe.** In the docker.lan clean room, run each subcommand's `--help` (proves no MCP/auth needed to load) — already partially done; extend to all 19.

Write Stage-0 results to a scratch JSON the workflow reads.

---

## Stage 1 — Finder fan-out (parallel; structured output)

Each finder reads only its assigned surface and returns `FINDING_SCHEMA`. Finders are blind to each other (multi-modal sweep).

**FINDING_SCHEMA**
```json
{ "type": "object", "required": ["findings"], "properties": { "findings": { "type": "array", "items": {
  "type": "object",
  "required": ["title","dimension","severity","location","claim","evidence"],
  "properties": {
    "title": {"type": "string"},
    "dimension": {"enum": ["1a","1b","1c","1d","1e","1f"]},
    "severity": {"enum": ["P0","P1","P2"]},
    "location": {"type": "string"},
    "claim": {"type": "string"},
    "evidence": {"type": "string"},
    "suggested_fix": {"type": "string"},
    "confidence": {"enum": ["high","medium","low"]}
  } } } } }
```

### Finders (13)

**1a Correctness** (5 finders, by cohesion cluster):
- [ ] `correct:board-core` — `lib/board.py`, `lib/board_provider.py`, `lib/cache.py`, `lib/capabilities.py`
- [ ] `correct:github` — `lib/github_provider.py` (1035 LOC; retry, etag, REST/GraphQL paths)
- [ ] `correct:kanbanflow` — `lib/kanbanflow_client.py`, `lib/kanbanflow_provider.py`, `lib/kf_number_index.py`
- [ ] `correct:migrate-graph` — `lib/migrate.py`, `lib/partition.py`, `lib/ties.py`
- [ ] `correct:session-batch` — `lib/session_lock.py`, `lib/worktree.py`, `lib/wrap_state.py`, the 6 batch scripts, the `jared` entry
  - Focus: logic errors, unhandled None/empty, off-by-one, resume/atomicity bugs, provider-contract violations, dual-import pitfalls.

**1b Security** (1 finder + Stage-0 secret scan):
- [ ] `security:injection-tokens` — every `subprocess`/`run_gh`/`run_graphql`/`gh api` call site: argument injection, shell=True, unsanitized interpolation into GraphQL/shell; token handling (does any path log/echo a token? the `GH_TOKEN`/PAT story; `KANBANFLOW_API_TOKEN` Bearer handling). Consumes Stage-0 secret-scan output.

**1c Doc↔code drift** (3 finders):
- [ ] `drift:command-stubs` — each of the 9 `commands/*.md` stubs vs. the CLI subcommands/flags it invokes: do documented flags/behaviors match `jared <cmd> --help` and the handler? (incl. F2 header-convention adjudication)
- [ ] `drift:skill-capabilities` — `SKILL.md` + `references/operations.md` capability/degradation prose vs. `lib/capabilities.py`; the three-tier model claims vs. reality
- [ ] `drift:references` — the other 14 reference docs + 4 asset templates vs. the code/behavior they describe; consumes Stage-0 backtick-path results

**1d Packaging/install** (1 finder):
- [ ] `pkg:install` — consumes Stage-0 metadata + hardcoded-path + `${CLAUDE_PLUGIN_ROOT}` results; reasons about cold-install UX, the PyYAML removal (F1), cross-platform (macOS/Windows: bashisms, path seps, `/dev/tcp`, `realpath`, `getent`), and the marketplace install instructions' accuracy.

**1e Test quality** (2 finders):
- [ ] `test:fakes-vs-contract` — does `tests/fake_kanbanflow.py` (and other fakes) match the live API contract? (known failure mode: fake returns full tasks, live returns `{taskId}`/null). Self-confirming classifier tests (author-string fed to author-signature).
- [ ] `test:coverage-gaps` — map the 19 subcommands + critical lib paths to test files; flag untested invariants and integration-vs-unit boundary gaps.

**1f Stranger-onboarding** (1 finder):
- [ ] `onboard:newcomer` — read **only** `README.md` then `getting-started.md` as a developer who has never seen jared. Can you get from `/plugin install` → first filed issue? Log every operator-coupling assumed-but-not-stated (board #4, findajob/trailscribe, bake-sites, `~/.secrets`, the PAT quirk, MCP-optional, `gh`-auth floor).

---

## Stage 2 — Adversarial verify (pipeline off each finder)

As each finder returns, its findings flow into verification without waiting for other finders (pipeline, no barrier).

- [ ] For each finding, spawn **2 skeptics** (3 for any `P0`) prompted: *"Try to refute this finding. Default to `refuted` if the evidence doesn't hold. For security/correctness, check whether the claimed code path is actually reachable."* Perspective-diverse for 1a/1b (one correctness-lens, one reachability-lens).
- [ ] Keep a finding iff **< majority** refute it. Record verdict + any severity correction.

**VERDICT_SCHEMA**
```json
{ "type": "object", "required": ["verdict","reasoning"], "properties": {
  "verdict": {"enum": ["confirmed","refuted","uncertain"]},
  "reasoning": {"type": "string"},
  "corrected_severity": {"enum": ["P0","P1","P2","unchanged"]} } }
```

---

## Stage 3 — Dedup, normalize, merge (JS in workflow; final synthesis agent)

- [ ] **Dedup** confirmed findings by `(normalized location, claim similarity)` — cross-dimension collisions (e.g., a hardcoded path flagged by both 1d and 1f) merge to one entry citing both dimensions.
- [ ] **Normalize severity** using verifier corrections; majority-of-3 for P0s.
- [ ] **Completeness critic** (1 agent): given the inventory + the confirmed set, ask "which inventory surface got zero findings *and* zero coverage — is that real cleanliness or an unreviewed gap?" Flag unreviewed surfaces for a follow-up finder round.
- [ ] **Merge** into the ledger's findings table (F3, F4, …) with severity, location, evidence, suggested fix, status=`confirmed`. Update each inventory row's `covered` marker.

---

## Output & exit

- [ ] Ledger updated with all confirmed Phase-1 findings; inventory `covered` markers set; commit + PR (closes #350).
- [ ] Session note on #350 summarizing counts by severity and the Phase-3 work-list shape.

**Exit criterion:** every inventory surface is either `covered` with findings or `covered` and clean per the completeness critic — no silent skips.

---

## Scale & cost estimate

- Stage 1: 13 finders. Stage 2: ~2.5 skeptics × (expected ~15–40 findings) ≈ 40–100 verify agents. Stage 3: ~1 critic + dedup (JS). **Total ≈ 55–115 agents**, concurrency-capped at ~10–16. Ultracode budget: acceptable; this is the comprehensive-review case the spec calls for.
- Wall-clock dominated by the slowest finder→verify chain (github_provider correctness, likely), not the sum.

## Documentation impact
- `docs/superpowers/reviews/2026-06-10-marketplace-readiness-ledger.md` — Stage 3 appends confirmed findings and sets the inventory `covered` markers. **The only doc Phase 1 writes.**
- No other surface changes in Phase 1: it *discovers* doc drift (dim 1c) but the *fixes* land in Phase 3, not here.
- `## Issue` linkage: #350's `## Planning` points at this plan; the plan archives to `docs/superpowers/plans/archived/2026-06/` when #350 closes.

## Verification gate
Phase 1 is done when: every inventory surface has its `covered` marker set; every confirmed finding is in the ledger with severity + evidence + suggested fix; the completeness critic reports no unreviewed surface; and the ledger commit + #350 PR open without closing keywords that would prematurely close downstream phases.

## Self-review (against spec § Phase 1)
- Dimensions a–f: all mapped to finders (1a→5, 1b→1+scan, 1c→3, 1d→1, 1e→2, 1f→1). ✓
- "Adversarially verified before landing": Stage 2 refute-skeptics. ✓
- "Full git-history secret scan": Stage 0. ✓
- "Every backtick path exists": Stage 0 sweep. ✓
- "Fakes masking live contracts" + "self-confirming tests": `test:fakes-vs-contract`. ✓
- No placeholders: schemas + per-finder surfaces are concrete. ✓
