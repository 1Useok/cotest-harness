#!/usr/bin/env bash
# 받은 과제 자료를 정리한다. inbox/ 에 받은 그대로 넣고 돌린다. 사용: scripts/inbox_scan.sh
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/inbox_scan.py" "$@"
