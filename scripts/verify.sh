#!/usr/bin/env bash
# 사용: scripts/verify.sh p1 [--fuzz 2000]
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/verify.py" "$@"
