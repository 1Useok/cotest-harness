#!/usr/bin/env bash
# 타이머. 사용: scripts/clock.sh start 150  |  scripts/clock.sh mark p1 solve|wait|resume|done
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/board.py" "$@"
