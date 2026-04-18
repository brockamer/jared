# Human-Readable Board Surface

The board's value is that a human glancing at it understands the state of the world. Detailed/machine-friendly content belongs in issue bodies, but the *surface* (column views, titles, first visible lines) must be scannable without expanding anything.

## Title templates

**Bug:** `Fix <thing>: <specific symptom>`
- ✅ `Fix sync_sheet.py: hidden fingerprint column drifting to column A`
- ❌ `sync_sheet has a bug`

**Enhancement:** `Add <thing>` or `Improve <thing>: <how>`
- ✅ `Add excluded_employers config + prefilter enforcement`
- ✅ `Improve scorer: tier-1 company boost only when JD is present`
- ❌ `More scorer improvements`

**Refactor:** `Refactor <thing> to <outcome>`
- ✅ `Refactor path resolution to use findajob.paths module`
- ❌ `Clean up paths`

**Documentation:** `Doc: <what>` or `Document <thing>`
- ✅ `Doc: refresh operations/architecture/scripts-reference for Docker deploy`
- ❌ `Update docs`

### Constraints
- ≤ 70 characters. GitHub truncates titles after ~50 chars in list views; 70 is a hard ceiling for readability.
- Verb-first. No "<thing> needs to happen" or "Feature: <thing>" — those waste scannable characters.
- No issue numbers in titles ("#12 follow-up") — the issue is linked via the `#N` mechanism already.

## Body template

```markdown
One-sentence summary. Put the entire "why" here, readable without expanding.

<details>
<summary>Scope details</summary>

Longer rationale, acceptance criteria, implementation notes, JSON payloads, code blocks — all the detail a reader *might* need but doesn't need up front.

</details>

## Dependencies
- Depends on: #N
- Blocks: #M

## Related
- Spec: [link]
- Parent: #P
```

### Constraints
- First paragraph is a single sentence. Readable in under 5 seconds.
- `<details>` blocks for scope, not for entire body — the collapsed block is "more if you want it", not "hidden by default."
- No headings deeper than `## ` at body top level. If you need `###` or deeper, put it inside a `<details>` block.
- Put dependency and parent/child references at the bottom, not top — they're reference metadata, not summary.

## When to break the template

- **Strategic / roadmap issues** (e.g., issue #58) often have longer bodies — they're reference docs in their own right. Use `##` headings for navigable sections, `<details>` for truly deep content.
- **Execution checklist issues** (e.g., deployment tickets) have long checkboxed bodies — keep the summary at top, checklist after, don't hide the checklist.

## Comment hygiene

- Don't use comments for status updates that should be STATUS or Priority field changes.
- Do use comments for: context added mid-work, decisions made during execution, links to related conversations, PRs that close the issue.
- When closing an issue, a short closing comment is nice but not required: "Shipped in #<PR>" or "Closed as obsolete because <reason>".

## Labels

Labels describe *kind*, not *priority* or *status*:

- `bug` / `enhancement` / `refactor` / `documentation` / `test` — type
- `blocked` — state (also note the blocker in body)
- `good-first-issue` — contributor signal
- `open-source` / `pipeline-quality` / `job-search` / `data-hygiene` — scope/domain

Do not use labels for:
- Priority (the Priority field is canonical; legacy `priority: high/med/low` labels should be stripped during grooming)
- Status (the Status field handles columns)
- Assignment (the Assignee field)

Labels are an additional axis to filter/group by — keep them high-signal.

## Scannability tests

After filing or editing an issue, read the first 100 characters. Can you tell:

1. What is this about?
2. What kind of work is it (bug / enhancement / refactor)?
3. What's it part of (area / domain)?

If any No, rewrite.

Read the issue in list view (board or `gh issue list` output). Does it fit on one line? If not, trim.
