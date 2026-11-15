#!/usr/bin/env bash
# 변형 시험: 테스트가 버그를 잡을 힘이 있는지 잰다. 사용: scripts/mutants.sh p1 [--max 60]
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/mutants.py" "$@"
