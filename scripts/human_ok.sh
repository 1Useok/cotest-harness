#!/usr/bin/env bash
# 사람이 눈으로 확인한 정답 사례를 기록한다. 사람이 "확인"이라고 말한 사례에만 쓴다.
# 사용: scripts/human_ok.sh p1 03_pending_cancel 06_replace
# tests/HUMAN_OK.txt 에 "사례이름 지문" 을 적는다. 지문은 그때의 입력과 기대 출력에서 만든다.
# 나중에 그 사례의 입력이나 기대 출력이 바뀌면 verify 가 "확인한 뒤 바뀐 사례"로 알려 준다.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
name="${1:?문제 이름 (예: p1)}"; shift
[ "$#" -ge 1 ] || { echo "사례 이름을 하나 이상 적어 주세요"; exit 2; }
tdir="$ROOT/problems/$name/tests"
[ -d "$tdir" ] || { echo "폴더가 없습니다: $tdir"; exit 2; }
python3 - "$tdir" "$@" <<'PY'
import hashlib, sys
from pathlib import Path
tdir = Path(sys.argv[1])
ok = tdir / "HUMAN_OK.txt"
old = {}
if ok.exists():
    for ln in ok.read_text(encoding="utf-8").splitlines():
        p = ln.split()
        if p and not ln.startswith("#"):
            old[p[0].removesuffix(".in")] = p[1] if len(p) > 1 else ""
rc = 0
for stem in sys.argv[2:]:
    stem = stem.removesuffix(".in").removesuffix(".out")
    if not (tdir / (stem + ".in")).exists() or not (tdir / (stem + ".out")).exists():
        print(f"없는 사례입니다: {stem}"); rc = 1; continue
    h = hashlib.sha256()
    for ext in (".in", ".out"):
        h.update((tdir / (stem + ext)).read_bytes().replace(b"\r\n", b"\n")); h.update(b"\0")
    old[stem] = h.hexdigest()[:12]
    print(f"기록: {stem} {old[stem]}")
ok.write_text("# 사람이 확인한 정답 사례 (사례이름 지문). scripts/human_ok.sh 가 적는다\n"
              + "".join(f"{k} {v}\n".rstrip(" ") if not v else f"{k} {v}\n" for k, v in old.items()),
              encoding="utf-8")
sys.exit(rc)
PY
