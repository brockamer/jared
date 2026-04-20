---
description: File a new issue with full metadata — two-step create + project add + Priority + any other required project fields, all in one flow.
---

Invoke the Jared skill to file a new issue properly. The two-step footgun (`gh issue create` not auto-adding to the board) is eliminated.

Flow:

1. **Gather inputs.** If the user's message already contains the content, extract: title, body summary, likely priority, values for any other categorical fields (e.g., Work Stream, if the project defines one — check `docs/project-board.md`), dependencies. If anything is unclear, ask ONE question at a time — don't front-load a form.

2. **Check for duplicates.** Run `gh search issues --repo <owner>/<repo>` on key terms. If a similar open issue exists, show it and ask whether to proceed, update the existing one, or close this request.

3. **Validate title.** ≤70 chars, verb-first. If the proposed title doesn't fit, propose a rewrite.

4. **Build the body** from `assets/issue-body.md.template`:
   - First paragraph: one-sentence summary
   - `## Current state` — "Not started."
   - `## Decisions` — "(none yet)"
   - `## Acceptance criteria` — in `<details>` block, list criteria
   - `## Depends on` / `## Blocks` — fill in if applicable, else "(none)"
   - `## Planning` — fill in if a plan/spec already exists, else "(none)"

5. **Create the issue.** Use `gh issue create` with the body.

6. **Add to the project board.** Use `gh project item-add` with the URL from step 5. Capture the item ID.

7. **Set Priority.** Use `gh project item-edit` with the Priority field ID and the appropriate option ID.

8. **Set any other required project fields.** For each additional single-select field documented in `docs/project-board.md` (e.g., Work Stream on projects that use one), set it via the same `gh project item-edit` pattern. Skip silently if the project doesn't define extra fields.

9. **Report.** Show the issue URL, confirm Priority and any required categorical fields are set, note whether `## Planning` references exist.

10. **If dependencies were specified**, create them via native GitHub issue dependencies (see `references/operations.md`), falling back to body convention if unavailable.

Defaults when the user doesn't specify:

- Priority: Medium (if the user doesn't name one)
- Other required fields (e.g., Work Stream): ask — never guess
- Labels: infer from content (e.g., "fix" → `bug`, "add" → `enhancement`, "refactor X" → `refactor`)

Do not file without Priority and all other required project fields set. An issue without required field values sorts to the bottom and disappears.
