#!/usr/bin/env bash
# 원본 대화 기록을 logs/raw/ 로 모으고 logs/MANIFEST.md 를 만든다. 사용: scripts/collect_logs.sh [--quiet]
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/collect_logs.py" "$@"
