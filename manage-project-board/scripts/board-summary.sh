#!/usr/bin/env bash
# board-summary.sh — print In Progress + Up Next for quick orientation
#
# Usage:
#   board-summary.sh                          # read project config from ./docs/project-board.md
#   board-summary.sh <owner> <project-number> # explicit args
#
# Output format:
#   == In Progress ==
#     #N [Priority/WorkStream] Title
#     ...
#   == Up Next ==
#     #N [Priority/WorkStream] Title
#     ...
#
# Exit codes:
#   0 — printed summary
#   1 — couldn't read project config or call gh

set -euo pipefail

OWNER="${1:-}"
PROJECT="${2:-}"

# If no args, try to read from docs/project-board.md
if [ -z "$OWNER" ] || [ -z "$PROJECT" ]; then
    CONFIG_FILE=""
    for p in docs/project-board.md PROJECT_BOARD.md .github/project-board.md; do
        if [ -f "$p" ]; then
            CONFIG_FILE="$p"
            break
        fi
    done
    if [ -z "$CONFIG_FILE" ]; then
        echo "board-summary: no project-board.md found and no args provided" >&2
        echo "Usage: $0 <owner> <project-number>" >&2
        exit 1
    fi

    # Extract owner + project number heuristically from the config file
    OWNER=$(grep -oE 'projects/[0-9]+' "$CONFIG_FILE" | head -1 | sed 's|projects/||' || true)
    PROJECT=$(grep -oE 'users/[a-zA-Z0-9_-]+/projects' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's|users/||;s|/projects||' || true)

    # That heuristic was backwards — parse the project URL from the file
    URL=$(grep -oE 'https://github.com/users/[a-zA-Z0-9_-]+/projects/[0-9]+' "$CONFIG_FILE" 2>/dev/null | head -1 || true)
    if [ -n "$URL" ]; then
        OWNER=$(echo "$URL" | sed -E 's|.*/users/([^/]+)/.*|\1|')
        PROJECT=$(echo "$URL" | sed -E 's|.*/projects/([0-9]+).*|\1|')
    fi

    if [ -z "$OWNER" ] || [ -z "$PROJECT" ]; then
        echo "board-summary: couldn't extract owner/project from $CONFIG_FILE" >&2
        echo "Config file must contain a URL like https://github.com/users/<owner>/projects/<N>" >&2
        exit 1
    fi
fi

# Pull and print
gh project item-list "$PROJECT" --owner "$OWNER" --limit 100 --format json 2>/dev/null \
  | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    items = data.get('items', [])
except Exception as e:
    print(f'board-summary: failed to parse gh output: {e}', file=sys.stderr)
    sys.exit(1)

by_status = {}
for i in items:
    s = i.get('status', 'No status')
    num = i.get('content', {}).get('number', '?')
    title = (i.get('title', '') or '')[:60]
    prio = i.get('priority', '-')
    ws = i.get('work Stream') or i.get('workStream') or '-'
    by_status.setdefault(s, []).append(f'#{num} [{prio}/{ws}] {title}')

for s in ['In Progress', 'Up Next']:
    print(f'== {s} ==')
    rows = by_status.get(s, [])
    if not rows:
        print('  (empty)')
    else:
        for line in sorted(rows, reverse=True):
            print(f'  {line}')
"
