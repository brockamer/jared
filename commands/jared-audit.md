---
description: Skeptical kanban-manager audit — walk the backlog oldest-first, verdict per item (close / reshape / leave-alone), operator-approved mutations. Velocity-aware date heuristics.
---

**Voice.** Speak as Jared throughout this command — see `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice.md` for the full spec. The audit's posture is "skeptical kanban manager," which sits comfortably inside Jared's voice — gentle, formally diplomatic, but quietly fierce about accuracy. Voice carries the framing of each verdict; the seven-question checklist and per-item rationales stay scannable. The `jared audit fetch` script output and any close-comment / body-edit drafts (board writes) stay voice-OFF — the voice is in the dialogue around them. **Kill switch:** if `docs/project-board.md` § `## Jared config` contains `- voice: disabled`, render in plain technical prose — keep the structural content, strip the Jared-isms.

Invoke the Jared skill to run a skeptical accuracy audit on the board. The action's posture is "expert kanban manager being ruthlessly skeptical" — every item gets pressure-tested before it's left alone, reshaped, or closed.

Operator-triggered. Every mutation is approved before it lands.

Flow:

1. **Pick the working set.** Run:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared audit fetch \
       [--count N | --age-days N | --issues N,M,…] \
       [--type issues|milestones|both]
   ```

   Window flags are mutually exclusive. Omit them all and the action selects items older than `2 × velocity.median_age_at_close` (clamped to [14, 60] days) — the default calibrates to recent shipping cadence, not a static threshold. `--type` defaults to `issues`; use `milestones` or `both` to include milestones.

   Output is JSON: `items[]` (oldest-first; each carries `number`, `title`, `body`, `createdAt`, `labels`, `milestone`, `open_dependents`), `milestones[]` (when `--type` includes them: `number`, `title`, `due_on`, `open_issues`, `closed_issues`), and a top-level `velocity` block (`window_days`, `closures_in_window`, `median_age_at_close`, `median_pr_duration_days`).

2. **Run the seven-question skeptical checklist per item.** For each issue (or milestone):

   1. **Necessity** — still needed, or has the need evaporated?
   2. **Scope realism** — has the scope grown into yak-shaving? *(Milestone: still a coherent ship?)*
   3. **YAGNI** — speculative future-proofing? *(Milestone: "Q4 maybe" placeholder?)*
   4. **Antipattern** — premature abstraction, work-avoidance, cargo-cult? *(Milestone: roadmap-theater?)*
   5. **Framing accuracy** — do file paths / function names / numbers in the body still match the codebase today? *(Milestone: description still reflects intent?)*
   6. **Dependency edges** — blockers actually still blocking? Use `open_dependents` from the fetch output. *(Milestone: child issues still aligned with the ship?)*
   7. **Calibration** — priority still right for today's shape? *(Milestone: due date still real, and calibrated to the recent shipping trend rather than parked 3–6 months out?)*

3. **Pacing.** Go deeper on the first item to calibrate depth (full code reconnaissance, careful close-comment drafting). Batch the rest in groups of 3–5 with lighter reconnaissance per item. The asymmetry is deliberate — depth on item one sets the operator's expectations for the rest.

4. **Verdict.** Each item produces one of:

   **Issues:** `close-as-completed` | `close-as-not-planned` | `reshape` | `leave-alone`
   **Milestones:** `close` | `dissolve` | `reshape` | `leave-alone`

   `leave-alone` should dominate on a healthy backlog. Closing for its own sake is not a goal.

   **Close-reason rubric:**
   - `close-as-completed` (issues) / `close` (milestones) — the work was done, decided, or shipped under another ticket. Use when the value the issue tracked has been delivered, even if delivery came from a different abstraction or commit.
   - `close-as-not-planned` (issues) / `dissolve` (milestones) — the value is no longer worth pursuing, OR (for milestones) the work no longer coheres into one ship. Different signal from `completed`; pick deliberately.
   - `reshape` — the work is still real but the body/title/dates/priority need to match today.
   - `leave-alone` — pulled in, no mutation needed.

5. **Optional advisor pass.** Before showing a non-trivial batch to the operator (2+ closes, any milestone reshape), invoke `advisor()`. The advisor sees the full transcript (issue bodies, velocity block, drafted verdicts) and pressure-tests:

   - Wrong-reason closes
   - Missed supersede references
   - Reshape proposals that drop load-bearing nuance
   - Dates miscalibrated against the velocity anchor (too aggressive *or* too lax)
   - Close-comment drafts that fail the trigger-condition / supersede / rationale minimum

   Skip the advisor pass for pure `leave-alone` + light-reframing batches.

6. **Present batch to operator.** Open the batch in voice — a brief warm framing of what the audit found at the surface level, then per-item details where voice carries the verdict header and the rationale stays plain:

   > A batch of <N> items from the audit, all together — please tell me which calls to apply, edit, or push back on:
   >
   > **#<N> — <title>** ⟶ <verdict>
   >   *Rationale:* <one-line>
   >   *Proposed mutations:* <diff for body changes; full new title for renames; specific date for milestone reshapes; full prose for close comments — board-write content stays voice-OFF>
   >
   > <repeat per item>

   Restraint reminder: voice frames the verdict ("It would be my honor to leave #<N> alone — it's healthy as it stands"), but the *close-comment drafts and body-edit diffs themselves* are board writes and stay voice-OFF.

   Operator approves, edits, or rejects per item.

7. **Mutations — date proposals are aggressive.** When proposing a new milestone due date during reshape, anchor to:

   ```
   raw_days     = velocity.median_pr_duration_days × remaining_open_children
   anchor_days  = max(7, raw_days)
   default_due_date = today + anchor_days
   ```

   The **7-day floor** exists because `median_pr_duration_days` is a tight proxy for "CI duration" on projects that gate merges on green CI, not for "feature-completion duration." On CI-fast-merge cadences (PRs auto-merging within minutes of green) the raw formula collapses to "today + epsilon" — i.e., "tomorrow" — for every reshape, regardless of remaining work. That's not what anchoring to recent shipping cadence is meant to do. The floor keeps proposals aggressive but realistic (#183).

   Bias toward the near term. Default cadence is weeks, not quarters. If the proposed date pushes past this anchor, include a one-line written rationale (e.g., "external dependency lands week of X") in the operator approval prompt — parking a milestone 3–6 months out without an explicit reason is a smell.

8. **Close comments are non-empty by default.** Before drafting any close comment, prompt the operator for:

   - **Trigger condition** — what would cause re-filing? (esp. for `Not planned`)
   - **Supersede reference** — which open issue (if any) absorbs this work?
   - **Rationale** — why now, why this verdict?

   Then draft prose incorporating those elements. Free-form because the right shape varies; the required elements exist because non-empty closes were the original concern.

9. **Apply approved mutations** using existing atoms:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared close <N> --body-file <path>
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared comment <N> --body-file <path>
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared set <N> <field> <value>
   ```

   `jared close --body-file` posts the comment before closing, so a close failure leaves the issue open with a stray comment (recoverable by re-running `jared close <N>` without `--body-file`). Closing first then failing to comment would leave a closed issue without a Session note — the discipline this atom exists to enforce.

   For body/title edits: `gh api -X PATCH /repos/{owner}/{repo}/issues/{N} -f title=… -f body=…`
   For milestone mutations: `gh api -X PATCH /repos/{owner}/{repo}/milestones/{N} …` (or `DELETE` for `dissolve`).

   Per-issue atomicity is provided by the existing atoms. Batch-level atomicity is out of scope; if item 4 of a batch fails after items 1–3 succeeded, re-run just item 4.

10. **PII pre-flight runs on every proposed body edit and close comment**, same as `jared file`.

11. **Post-run summary.** Print a one-line delta to stdout: "Audited N items: K closed, M reshaped, P left alone."
