"""Session-presence locking for parallel jared sessions (#231, #236, #259, #376).

Every active `/jared-start` writes a JSON lock file at
`<repo>/.git/jared/session-<issue>.lock` recording the issue, start time, optional
`--session N` value, worktree path, and the writing process's PID (diagnostic only).
The lock is keyed by issue, not PID: the CLI subprocess that writes the lock exits
immediately, so a PID-keyed file would be dead-on-arrival and the B-leg refusal would
never fire (the original #231/#236 implementation had this defect — #259 fixes it).

Locks live until explicitly cleared by `/jared-wrap` (or `jared session-lock-clear
--issue N`). A crashed session leaves its lock on disk; the next `/jared-start` will
detect it and refuse with guidance, including the recorded PID so the operator can
verify and force-clear if appropriate.

Locks live under the git common dir, not in the working tree (#376). This is a
correctness requirement, not tidiness: `list_active_locks` does no liveness sweep,
so every lock file on disk counts as a live sibling. A lock committed from a
working-tree path would therefore make `/jared-start` refuse in every clone of
that project, forever, for a session that never existed. Git does not track the
contents of its own directory, so this location removes the failure mode rather
than guarding against it. Locks written before #376 at `<repo>/.jared/`
are ignored, never migrated or deleted — a tracked one is not jared's file to
remove, and would return on the next checkout regardless.

See docs/superpowers/specs/archived/2026-05/2026-05-23-multi-session-impl-design.md
for the original design; this module's identity model was reworked in #259 after
empirical evidence that PID-keyed locks were stale-on-arrival.
"""

from __future__ import annotations

import contextlib
import enum
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


class NotAGitCheckout(Exception):
    """Raised when a `repo_root` has no `.git` directory to anchor locks under."""


NON_GIT_NOTICE = (
    "jared: session lock skipped — {root} has no .git directory. "
    "Sibling detection guards a shared .git/HEAD, which does not exist here. "
    "Do not run `git init` to satisfy it."
)


def is_git_checkout(repo_root: Path) -> bool:
    """True when `repo_root` has a `.git` directory to anchor locks under.

    The single predicate the whole protocol asks (#425). `write_lock` raises on
    its negation and the CLI skips on it, so the read, write and clear halves
    cannot drift apart the way they did before — `session-resolve` returning
    `PROCEED_SOLO` while `session-lock-write` refused the write it had promised.

    Resolves for the same reason `_lock_dir` does: REPO_ROOT collapses to a
    relative '.' in the main checkout (#284), and an unresolved check would
    report False where `write_lock` succeeds.
    """
    return (repo_root.resolve() / ".git").is_dir()


def non_git_notice(repo_root: Path) -> str:
    """The one skip notice all three lock subcommands print on a non-git root.

    Deliberately **not** a `degraded:` line. That shape answers "can this backend
    express this concept?", and this condition does not depend on the backend at
    all — a GitHub-backend project run from a bare directory hits it, and a
    KanbanFlow board inside a checkout does not. Tagging it as a capability would
    file a git-axis condition under a backend-keyed heading, which is the
    mis-tagging cost ledger findings F11/F27/F53/F57 record. See #425.
    """
    return NON_GIT_NOTICE.format(root=repo_root.resolve())


@dataclass(frozen=True)
class Lock:
    """A session-presence record on disk."""

    pid: int
    started: str
    session: int | None
    worktree_path: str | None
    issue: int


def _lock_dir(repo_root: Path) -> Path:
    # Every caller derives `repo_root` as `dirname(git rev-parse --git-common-dir)`,
    # so `<repo_root>/.git` is the common dir by contract — no subprocess needed to
    # find it, and this stays a pure path computation. The common dir is also exactly
    # the scope the sibling detector reasons about: it is what linked worktrees share,
    # which is the trap `--session N` exists to avoid (#376).
    #
    # `.resolve()` anchors the lock dir at the true (absolute) repo root even when
    # the caller passes a relative root — e.g. REPO_ROOT collapsing to '.' in the
    # main checkout (#284). A cwd-relative lock dir breaks cross-session sibling
    # detection. Every lock path flows through here, so this is the single net.
    return repo_root.resolve() / ".git" / "jared"


def _lock_path(repo_root: Path, issue: int) -> Path:
    return _lock_dir(repo_root) / f"session-{issue}.lock"


def write_lock(repo_root: Path, lock: Lock) -> Path:
    """Atomically write a lock file for this session. Returns the path.

    Raises NotAGitCheckout if `repo_root` is not a checkout root. Writes are strict
    where reads are tolerant: `mkdir(parents=True)` would otherwise *create* a
    `.git/` in a plain directory, turning it into something git half-recognises.
    Reachable — the `/jared-start` stub's REPO_ROOT derivation collapses to cwd
    when `git rev-parse` fails. Since #425 the CLI checks `is_git_checkout` and
    skips before calling this, so the guard is the backstop rather than the
    operator-facing path; it stays because it is what stops `mkdir(parents=True)`
    from conjuring a `.git/`.
    """
    if not is_git_checkout(repo_root):
        raise NotAGitCheckout(f"not a git checkout root (no .git directory): {repo_root.resolve()}")
    lockdir = _lock_dir(repo_root)
    lockdir.mkdir(parents=True, exist_ok=True)
    path = _lock_path(repo_root, lock.issue)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(lock)))
    os.replace(tmp, path)
    return path


def read_lock(path: Path) -> Lock | None:
    """Read and parse a lock file. Returns None if absent or malformed."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        raw_session = payload["session"]
        raw_wt = payload["worktree_path"]
        return Lock(
            pid=int(payload["pid"]),
            started=str(payload["started"]),
            session=None if raw_session is None else int(raw_session),
            worktree_path=None if raw_wt is None else str(raw_wt),
            issue=int(payload["issue"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def clear_lock(repo_root: Path, issue: int) -> None:
    """Remove the lock file for this issue. No-op if absent."""
    path = _lock_path(repo_root, issue)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def list_active_locks(repo_root: Path) -> list[Lock]:
    """Enumerate all session locks on disk for this repo.

    Walks `<repo>/.git/jared/session-*.lock` and reads each. Malformed lock files
    are silently skipped — they may be partial writes from a crashed write
    that didn't reach os.replace. A missing `.git/` or `.git/jared/` yields no
    siblings: reads stay tolerant where writes are strict.

    Locks at the pre-#376 working-tree path `<repo>/.jared/` are not read at all,
    so a committed one can no longer manufacture a false sibling. They are left
    on disk: jared must not delete a file from a consuming project's tree, and a
    tracked lock would reappear on the next checkout anyway. (The pre-#259
    PID-keyed migration sweep went with them — it could only ever fire against
    `.jared/`, which nothing reads now.)

    No PID-liveness sweep is performed: the CLI subprocess's PID (only recorded
    diagnostically) is always dead by the time anything reads the file. A
    crashed session leaves its lock on disk; the operator clears it explicitly
    with `jared session-lock-clear --issue N` when the next `/jared-start`
    surfaces the orphan.
    """
    lockdir = _lock_dir(repo_root)
    if not lockdir.exists():
        return []
    active: list[Lock] = []
    for path in sorted(lockdir.glob("session-*.lock")):
        lock = read_lock(path)
        if lock is None:
            continue
        active.append(lock)
    return active


class Action(enum.Enum):
    """Resolution outcome for a `/jared-start` invocation."""

    PROCEED_SOLO = "proceed_solo"
    PROCEED_MULTI = "proceed_multi"
    PROCEED_ACK_RISK = "proceed_ack_risk"
    REFUSE_BLEG = "refuse_bleg"
    REFUSE_DUP_SESSION_N = "refuse_dup_session_n"
    REFUSE_CONFLICTING_FLAGS = "refuse_conflicting_flags"


@dataclass(frozen=True)
class Flags:
    """Operator-supplied flags to `/jared-start`."""

    session: int | None
    no_worktree: bool


def resolve_action(siblings: list[Lock], flags: Flags) -> Action:
    """Decide what `/jared-start` should do given current sibling locks and flags.

    Maps to the six-row action table in
    docs/superpowers/specs/archived/2026-05/2026-05-23-multi-session-impl-design.md § D3.
    Pure function — no I/O, no side effects.
    """
    # --session and --no-worktree are mutually exclusive: one says "isolate me",
    # the other says "I'm accepting the shared-HEAD risk".
    if flags.session is not None and flags.no_worktree:
        return Action.REFUSE_CONFLICTING_FLAGS

    if not siblings:
        if flags.session is not None:
            return Action.PROCEED_MULTI
        return Action.PROCEED_SOLO

    # At least one live sibling.
    if flags.no_worktree:
        # Operator acknowledged the trap explicitly.
        return Action.PROCEED_ACK_RISK

    if flags.session is None:
        # Sibling exists, no flag → refuse with guidance.
        return Action.REFUSE_BLEG

    # flags.session is not None — multi-session opt-in. Two-pass scan so
    # the refusal reason is deterministic regardless of sibling order.
    # Solo-sibling refusal takes priority: it surfaces the actual trap shape
    # (sibling on shared HEAD) which is more actionable than a flag collision.
    for sib in siblings:
        if sib.session is None:
            return Action.REFUSE_BLEG
    for sib in siblings:
        if sib.session == flags.session:
            return Action.REFUSE_DUP_SESSION_N

    return Action.PROCEED_MULTI
