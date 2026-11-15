#!/usr/bin/env bash
# 현황판. 사용: scripts/board.sh [--watch]
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/board.py" "$@"
