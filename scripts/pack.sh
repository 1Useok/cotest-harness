#!/usr/bin/env bash
# 제출 묶음을 만든다(답안 + AI 사용 내역 zip + 목록). 메일을 보내기 직전에 돌린다. 사용: scripts/pack.sh
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/pack.py" "$@"
