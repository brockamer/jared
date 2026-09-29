"""Pick the next item for a bare `/jared-start` (#516).

The rule, in order:

1. Resume the first In Progress item that holds no session lock and has no
   open blocker.
2. Otherwise take the first Up Next item that holds no session lock, has no
   open blocker and is pullable.

Both steps walk the items in board order and see only the session partition:
every item when no session is given, the `session-N`-labeled items under
`--session N`. Each item passed over before the pick is reported with its
reason, so the operator can see why the top of Up Next was not taken.

Decisions recorded on #516:

- **A blocker is open when its number is in the open-item set.** That holds on
  both backends: the GitHub edge query filters only the dependent side, and a
  KanbanFlow task in Done is outside the open set. It differs from
  `stage.has_no_open_blockers`, which reads an unknown blocker as open. Here an
  open blocker that is not on the board reads as not blocking — a filing
  defect for `/jared-groom`, not a pick concern.
- **Every lock on disk at pick time belongs to another session.** `/jared-start`
  writes this session's lock after the pick, so a locked item is a sibling's or
  a crashed session's, and it is skipped either way.
- **The WIP cap is not part of the pick.** `/jared-start` step 2 owns it.

Pure: no I/O of its own. `body_of` is the one read, and the caller supplies it,
because GitHub's open-items query carries no body. It is called only for Up
Next items reached before the pick.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .pullable import is_pullable, not_pullable_reason

if TYPE_CHECKING:
    from .board_provider import BoardItem, Edge

RULES = {
    1: "resume the first In Progress item that holds no session lock and has no open blocker",
    2: "the first Up Next item that holds no session lock, has no open blocker and is pullable",
}


@dataclass(frozen=True)
class Skip:
    number: int
    status: str
    reason: str


@dataclass(frozen=True)
class Pick:
    number: int | None
    rule: int | None
    session: int | None = None
    skipped: list[Skip] = field(default_factory=list)


def _lock_reason(number: int, repo_root: str) -> str:
    return (
        "held by a session lock — another session is on it, or one ended without "
        "/jared-wrap; if no session is live, run: "
        f"jared session-lock-clear --repo-root {repo_root} --issue {number}"
    )


def choose(
    items: Sequence[BoardItem],
    *,
    edges: Iterable[Edge],
    locked: Collection[int],
    session: int | None = None,
    body_of: Callable[[BoardItem], str] | None = None,
    repo_root: str = "<repo-root>",
) -> Pick:
    """Apply the rule to `items`, which must be in board order.

    `repo_root` only fills the clear command in a lock skip reason, so the
    operator can run it as printed.
    """
    if session is not None:
        label = f"session-{session}"
        partition = [item for item in items if label in item.labels]
    else:
        partition = list(items)

    open_numbers = {item.number for item in items}
    blockers: dict[int, set[int]] = {}
    for edge in edges:
        if edge.blocker in open_numbers:
            blockers.setdefault(edge.dependent, set()).add(edge.blocker)

    def read_body(item: BoardItem) -> str:
        return body_of(item) if body_of is not None else item.body

    skipped: list[Skip] = []
    for rule, status in ((1, "In Progress"), (2, "Up Next")):
        for item in partition:
            if item.status != status:
                continue
            reason: str | None = None
            if item.number in locked:
                reason = _lock_reason(item.number, repo_root)
            elif item.number in blockers:
                refs = ", ".join(f"#{n}" for n in sorted(blockers[item.number]))
                reason = f"blocked by open {refs}"
            elif rule == 2:
                row = {"body": read_body(item), "labels": item.labels}
                if not is_pullable(row):
                    reason = not_pullable_reason(row)
            if reason is None:
                return Pick(number=item.number, rule=rule, session=session, skipped=skipped)
            skipped.append(Skip(number=item.number, status=status, reason=reason))
    return Pick(number=None, rule=None, session=session, skipped=skipped)


def render_pick(pick: Pick) -> list[str]:
    """The `Pick:` line, then one `Skipped:` line per item passed over."""
    scope = f" (session-{pick.session} partition)" if pick.session is not None else ""
    if pick.number is None or pick.rule is None:
        head = (
            f"Pick: none — no In Progress or Up Next item qualifies{scope}; "
            "run /jared-stage to promote a Backlog item"
        )
    else:
        head = f"Pick: #{pick.number} — rule {pick.rule}: {RULES[pick.rule]}{scope}"
    return [head] + [f"Skipped: #{s.number} [{s.status}] — {s.reason}" for s in pick.skipped]
