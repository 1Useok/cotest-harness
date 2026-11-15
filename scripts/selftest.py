#!/usr/bin/env python3
"""하네스 자체 시험.

1. 예제 문제(selftest/s1)의 올바른 답안이 FAIL 없이 통과하는지 본다.
2. 일부러 버그를 넣은 답안마다 FAIL 이 나는지, 어느 검사가 잡았는지 본다.
3. 하네스 자신의 실패 경로를 본다: 알려진 오답, 생략된 검사, 무작위 0회, Codex 호출 실패,
   실행되지 않은 줄, 변형 시험.

사용: python3 scripts/selftest.py [--fuzz 500] [--quick]   (--quick 은 2번을 건너뛴다)
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S1 = ROOT / "selftest" / "s1"
OUT = ROOT / "selftest" / "build"
fuzz = sys.argv[sys.argv.index("--fuzz") + 1] if "--fuzz" in sys.argv else "500"
quick = "--quick" in sys.argv

sys.path.insert(0, str(ROOT / "selftest"))
import mutate  # noqa: E402

IGNORE = shutil.ignore_patterns("build", "fuzz_fail", "VERIFY.*", "MUTANTS.*", "__pycache__")


def verify(pdir, *extra):
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify.py"), str(pdir), *extra],
                       capture_output=True, text=True)
    data = json.loads((pdir / "VERIFY.json").read_text(encoding="utf-8"))
    caught = [r["check"] for r in data["rows"] if r["status"] == "FAIL"]
    return p.returncode, data, caught


def copy_s1(name):
    d = OUT / name / "s1"
    shutil.copytree(S1, d, ignore=IGNORE)
    return d


def seed_xcheck(pdir):
    """예제 문제에 "다른 모델이 따로 구한 출력"을 만들어 둔다(기대 출력과 같은 것). 교차 확인 행의 기준 상태다."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import xcheck
    xd = pdir / "xcheck"
    if xd.exists():
        shutil.rmtree(xd)
    xd.mkdir()
    index = {}
    for t in sorted((pdir / "tests").glob("*.in")):
        shutil.copy(t.with_suffix(".out"), xd / f"{t.stem}.out")
        index[t.stem] = {"in_sha": xcheck.sha(t.read_bytes()), "model": "자체 시험", "time": "-"}
    (xd / "INDEX.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def main():
    # 윈도우 줄바꿈(\r\n) 사례는 편집기에서 깨지기 쉬워 여기서 만든다.
    (S1 / "tests" / "06_crlf.in").write_bytes(b"T A 100\r\nN 1 A B 100 1\r\nF 1 1\r\n")
    (S1 / "tests" / "06_crlf.out").write_bytes(b"TICK A 100 OK\nACCEPT 1\nFILL 1 1 0\nPOS A 1\n")
    seed_xcheck(S1)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    ok = True
    rc, data, caught = verify(S1, "--fuzz", fuzz)
    print(f"올바른 답안: {data['verdict']}" + (f"  <- 실패한 검사: {caught}" if caught else "")
          + (f"  (조건: {'; '.join(data['conditions'])})" if data.get("conditions") else ""))
    if rc != 0 or data["verdict"] != "PASS":
        ok = False

    if not quick:
        print()
        print("| 넣은 버그 | 설명 | 결과 | 잡은 검사 |")
        print("|---|---|---|---|")
        for name, (desc, _, _) in mutate.MUTANTS.items():
            d = copy_s1(name)
            mutate.sys.argv = ["mutate.py", str(S1 / "s1.cpp"), name, str(d / "s1.cpp")]
            mutate.main()
            rc, data, caught = verify(d, "--fuzz", fuzz, "--no-cov")
            result = "잡음" if rc == 1 else "**놓침**"
            if rc != 1:
                ok = False
            print(f"| {name} | {desc} | {result} | {', '.join(caught) if caught else '-'} |")

    # ---- 하네스 자신의 실패 경로 ----
    print()
    print("| 하네스 시험 | 기대 | 결과 |")
    print("|---|---|---|")

    def row(name, expect, passed, detail=""):
        nonlocal ok
        if not passed:
            ok = False
        print(f"| {name} | {expect} | {'통과' if passed else '**실패**'} {detail} |")

    submit = ROOT / "submit" / "s1.cpp"
    had_submit = submit.exists()

    # h1: 알려진 오답이 있으면 조건부, 승인 없이는 제출로 복사하지 않는다
    d = copy_s1("h1_known_fail")
    (d / "known_fail").mkdir()
    (d / "known_fail" / "k1.in").write_bytes(b"T A 100\n")
    (d / "known_fail" / "k1.out").write_bytes(b"TICK A 100 WRONG\n")
    if not had_submit and submit.exists():
        submit.unlink()
    rc, data, _ = verify(d, "--fuzz", "200", "--no-cov", "--final")
    copied1 = data.get("copied")
    row("h1 알려진 오답", "조건부, 종료 코드 2, 복사 안 함",
        data["verdict"] == "조건부" and rc == 2 and not copied1, f"({data['verdict']}, rc {rc})")
    rc, data, _ = verify(d, "--fuzz", "200", "--no-cov", "--final", "--accept", "자체 시험")
    row("h1b 사람의 승인", "승인 사유가 있으면 복사", rc == 0 and data.get("copied") and data.get("accept") == "자체 시험")
    if not had_submit and submit.exists():
        submit.unlink()

    # h2: 무작위 0회는 완전한 PASS 가 아니다
    d = copy_s1("h2_fuzz0")
    rc, data, _ = verify(d, "--fuzz", "0", "--no-cov", "--final")
    row("h2 무작위 0회", "조건부, 복사 안 함", data["verdict"] == "조건부" and rc == 2 and not data.get("copied"),
        f"({data['verdict']}, rc {rc})")

    # h3: 검사기·생성기·독립 구현이 없으면 조건부
    d = copy_s1("h3_missing")
    for f in ("check.py", "gen.py", "alt.cpp"):
        (d / f).unlink()
    rc, data, _ = verify(d, "--no-cov", "--final")
    row("h3 검사 생략", "조건부, 복사 안 함", data["verdict"] == "조건부" and rc == 2 and not data.get("copied"),
        f"(조건 {len(data['conditions'])}개)")

    # h4: 사람의 확인은 없어도 된다. 다른 모델의 교차 확인이 없으면 조건부다.
    d = copy_s1("h4_no_human")
    (d / "tests" / "HUMAN_OK.txt").unlink()
    rc, data, _ = verify(d, "--fuzz", "200", "--no-cov")
    no_human_pass = data["verdict"] == "PASS"
    shutil.rmtree(d / "xcheck")
    rc, data, _ = verify(d, "--fuzz", "200", "--no-cov")
    row("h4 교차 확인 없음", "사람 확인이 없어도 PASS, 교차 확인이 없으면 조건부",
        no_human_pass and data["verdict"] == "조건부" and rc == 0, f"(사람 확인 없이 PASS {no_human_pass})")

    # h5: 시험이 건드리지 않은 줄을 찾아낸다
    d = copy_s1("h5_coverage")
    for t in (d / "tests").glob("0[2-6]_*"):
        t.unlink()
    rc, data, _ = verify(d, "--fuzz", "0")
    cov = [r for r in data["rows"] if r["check"] == "실행되지 않은 줄"]
    row("h5 실행되지 않은 줄", "테스트를 줄이면 '확인'으로 알린다", bool(cov) and cov[0]["status"] == "확인",
        f"({cov[0]['detail'][:40]}…)" if cov else "(행 없음)")

    # h6: Codex 가 오류로 끝나면 실패로 처리하고, 있던 결과물을 덮어쓰지 않는다
    d = copy_s1("h6_codex_fail")
    fake = OUT / "fake_codex.sh"
    fake.write_text(
        '#!/usr/bin/env bash\n'
        'if [ "${1:-}" = "--version" ]; then echo fake-codex; exit 0; fi\n'
        'dir=""; while [ $# -gt 0 ]; do if [ "$1" = "-C" ]; then dir="$2"; fi; shift; done\n'
        'if [ -n "${FAKE_LS:-}" ]; then ls "$dir" > "$FAKE_LS"; fi\n'
        'if [ -d "$dir/cases" ]; then mkdir -p "$dir/xcheck"; echo notes > "$dir/XCHECK_NOTES.md"\n'
        '  for f in "$dir"/cases/*.in; do b=$(basename "$f" .in); cp "$FAKE_XDIR/$b.out" "$dir/xcheck/$b.out"; done\n'
        '  if ls "$dir"/*.cpp > /dev/null 2>&1 || ls "$dir"/cases/*.out > /dev/null 2>&1 || [ -d "$dir/tests" ]; then exit 9; fi\n'
        '  exit 0; fi\n'
        'printf "%s" "${FAKE_BODY:-int main(}" > "$dir/alt.cpp"\n'
        'if [ -n "${FAKE_REVIEW:-}" ]; then printf "지적 1건\\n작성 중\\n" > "$dir/REVIEW_codex.md"; fi\n'
        'exit "${FAKE_RC:-42}"\n', encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    before = (d / "alt.cpp").read_bytes()
    env = dict(os.environ, CODEX_BIN=str(fake), FAKE_RC="42")
    p = subprocess.run(["bash", str(ROOT / "scripts" / "codex_ask.sh"), "alt", str(d)],
                       capture_output=True, text=True, env=env)
    row("h6 Codex 오류 종료", "종료 코드 4, alt.cpp 그대로",
        p.returncode == 4 and (d / "alt.cpp").read_bytes() == before, f"(rc {p.returncode})")
    env = dict(os.environ, CODEX_BIN=str(fake), FAKE_RC="0")
    p = subprocess.run(["bash", str(ROOT / "scripts" / "codex_ask.sh"), "alt", str(d)],
                       capture_output=True, text=True, env=env)
    row("h6b 컴파일 안 되는 alt", "종료 코드 4, alt.cpp 그대로",
        p.returncode == 4 and (d / "alt.cpp").read_bytes() == before, f"(rc {p.returncode})")
    # h6c: 속도 사전을 누구에게 얼마나 보여 주는가. 리뷰어는 전부, 독립 구현은 "큰 입력 모양" 절만.
    ls_alt, ls_review = OUT / "fake_ls_alt.txt", OUT / "fake_ls_review.txt"
    subprocess.run(["bash", str(ROOT / "scripts" / "codex_ask.sh"), "alt", str(d)],
                   capture_output=True, text=True, env=dict(env, FAKE_LS=str(ls_alt)))
    subprocess.run(["bash", str(ROOT / "scripts" / "codex_ask.sh"), "review", str(d)],
                   capture_output=True, text=True, env=dict(env, FAKE_LS=str(ls_review)))
    seen_alt = ls_alt.read_text().split() if ls_alt.exists() else []
    seen_review = ls_review.read_text().split() if ls_review.exists() else []
    row("h6c 속도 사전 전달", "리뷰어는 PERF.md, 독립 구현은 BIG_SHAPES.md 만",
        "PERF.md" in seen_review and "TRAPS.md" in seen_review
        and "BIG_SHAPES.md" in seen_alt and "PERF.md" not in seen_alt,
        f"(alt {'BIG_SHAPES.md' in seen_alt}, review {'PERF.md' in seen_review})")
    # h6d: 리뷰가 시간 초과(124)로 끊겨도 쓰다 만 REVIEW_codex.md 가 있으면 부분 결과로 받는다. 없으면 실패.
    rv = d / "REVIEW_codex.md"
    p = subprocess.run(["bash", str(ROOT / "scripts" / "codex_ask.sh"), "review", str(d)],
                       capture_output=True, text=True, env=dict(env, FAKE_RC="124", FAKE_REVIEW="1"))
    part_ok = (p.returncode == 0 and "OK(부분):" in p.stdout and rv.exists()
               and rv.read_text(encoding="utf-8").startswith("> 부분 결과"))
    if rv.exists():
        rv.unlink()
    p = subprocess.run(["bash", str(ROOT / "scripts" / "codex_ask.sh"), "review", str(d)],
                       capture_output=True, text=True, env=dict(env, FAKE_RC="124"))
    row("h6d 끊긴 리뷰", "쓴 파일이 있으면 OK(부분), 없으면 종료 코드 4",
        part_ok and p.returncode == 4 and not rv.exists(), f"(부분 {part_ok}, 파일 없음 rc {p.returncode})")
    for f in (ROOT / "logs").glob("codex_*_s1_*.log"):
        if "fake-codex" in f.read_text(encoding="utf-8", errors="replace")[:400]:
            f.unlink()

    # h7: 변형 시험. 테스트가 충분하면 대부분 잡고, 테스트를 줄이면 살아남는 것이 늘어난다
    d = copy_s1("h7_mutants_full")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "mutants.py"), str(d), "--max", "40"],
                   capture_output=True, text=True)
    full = json.loads((d / "MUTANTS.json").read_text(encoding="utf-8"))
    d2 = copy_s1("h7_mutants_weak")
    for t in (d2 / "tests").glob("0[2-6]_*"):
        t.unlink()
    (d2 / "gen.py").unlink()
    subprocess.run([sys.executable, str(ROOT / "scripts" / "mutants.py"), str(d2), "--max", "40"],
                   capture_output=True, text=True)
    weak = json.loads((d2 / "MUTANTS.json").read_text(encoding="utf-8"))
    row("h7 변형 시험", "전체 테스트가 예제 하나보다 더 많이 잡는다",
        full["total"] > 0 and full["killed"] > weak["killed"],
        f"(전체 {full['killed']}/{full['total']}, 예제만 {weak['killed']}/{weak['total']})")

    # h8: 사람이 확인한 뒤 기대 출력이 바뀐 사례는 세지 않고 조건부로 알린다
    d = copy_s1("h8_human_changed")
    (d / "tests" / "HUMAN_OK.txt").write_text("01_example 000000000000\n", encoding="utf-8")
    rc, data, _ = verify(d, "--fuzz", "200", "--no-cov")
    changed = [r for r in data["rows"] if r["check"] == "사람이 확인한 뒤 바뀐 사례"]
    row("h8 확인 뒤 바뀐 사례", "조건부, 따로 알린다", data["verdict"] == "조건부" and bool(changed))

    # h9: 다른 모델이 쓴 두 번째 생성기를 번갈아 쓰고, 고장 난 생성기는 빼고 계속 간다
    d = copy_s1("h9_gen2")
    shutil.copy(d / "gen.py", d / "gen2.py")
    rc, data, _ = verify(d, "--fuzz", "200", "--no-cov")
    fz = [r for r in data["rows"] if r["check"].startswith("3층")]
    both = bool(fz) and "gen2.py(다른 모델이 씀) 100회" in fz[0]["detail"]
    (d / "gen2.py").write_text("def gen(rng):\n    raise RuntimeError('broken')\n", encoding="utf-8")
    rc2, data2, _ = verify(d, "--fuzz", "200", "--no-cov")
    fz2 = [r for r in data2["rows"] if r["check"].startswith("3층")]
    dropped = bool(fz2) and fz2[0]["status"] == "PASS" and "중간에 뺐다" in fz2[0]["detail"]
    row("h9 두 번째 생성기", "번갈아 쓰고, 고장 나면 빼고 계속", both and dropped,
        f"(번갈아 {both}, 고장 처리 {dropped})")

    # h10: 아무것도 검사하지 않는 검사기는 "검사기의 힘"에서 드러난다
    d = copy_s1("h10_weak_checker")
    (d / "check.py").write_text("def check(inp, out):\n    return []\n", encoding="utf-8")
    rc, data, _ = verify(d, "--fuzz", "200", "--no-cov")
    ck = [r for r in data["rows"] if r["check"].startswith("검사기의 힘")]
    row("h10 약한 검사기", "조건부, '확인'으로 알린다",
        data["verdict"] == "조건부" and bool(ck) and ck[0]["status"] == "확인",
        f"({ck[0]['detail'][:36]}…)" if ck else "(행 없음)")

    # h11: 큰 입력을 여러 개 받고, 입력이 2배일 때 시간이 4배가 되는 답안을 알린다
    d = copy_s1("h11_growth")
    src = (d / "s1.cpp").read_text(encoding="utf-8")
    marker = "int main("
    slow = ("#include <vector>\nstatic std::vector<int> g_slow;\n"
            "static void slow_step() { g_slow.push_back(1); volatile long long s = 0; "
            "for (int x : g_slow) s += x; }\n")
    pos = src.index(marker)
    brace = src.index("{", src.index("getline", pos))
    src = src[:pos] + slow + src[pos:brace + 1] + " slow_step();" + src[brace + 1:]
    (d / "s1.cpp").write_text(src, encoding="utf-8")
    with (d / "gen.py").open("a", encoding="utf-8") as f:
        f.write("\n\ndef gen_big(rng):\n    return ['T A 100\\n' * 60000, 'T A 100\\n' * 60000]\n")
    rc, data, _ = verify(d, "--fuzz", "50", "--no-cov")
    bg = [r for r in data["rows"] if r["check"] == "큰 입력 실행 시간"]
    row("h11 느려지는 답안", "'확인', 조건부", bool(bg) and bg[0]["status"] == "확인" and data["verdict"] == "조건부",
        f"({bg[0]['detail'][:60]}…)" if bg else "(행 없음)")
    mem_normal = [r for r in data["rows"] if r["check"] == "큰 입력 메모리"]

    # h15: 큰 입력에서 최대 메모리를 재고, 줄마다 메모리를 쌓아 두는 답안을 알린다
    d = copy_s1("h15_memory")
    src = (d / "s1.cpp").read_text(encoding="utf-8")
    hog = ("#include <string>\n#include <vector>\nstatic std::vector<std::string> g_hog;\n"
           "static void hog_step() { g_hog.emplace_back(4096, 'x'); }\n")
    pos = src.index(marker)
    brace = src.index("{", src.index("getline", pos))
    src = src[:pos] + hog + src[pos:brace + 1] + " hog_step();" + src[brace + 1:]
    (d / "s1.cpp").write_text(src, encoding="utf-8")
    with (d / "gen.py").open("a", encoding="utf-8") as f:
        f.write("\n\ndef gen_big(rng):\n    return ['T A 100\\n' * 90000]\n")
    rc, data, _ = verify(d, "--fuzz", "50", "--no-cov")
    mem = [r for r in data["rows"] if r["check"] == "큰 입력 메모리"]
    # 보통 답안의 값이 작게 나오는지도 본다(검증 프로그램 자신의 메모리가 섞이면 수십 MB 로 나온다)
    m_small = re.search(r"(\d+)MB", mem_normal[0]["detail"]) if mem_normal else None
    row("h15 메모리를 쌓는 답안", "보통 답안은 PASS 이고 30MB 아래, 쌓는 답안은 '확인'",
        bool(mem_normal) and mem_normal[0]["status"] == "PASS" and bool(m_small) and int(m_small.group(1)) < 30
        and bool(mem) and mem[0]["status"] == "확인",
        f"(보통 {m_small.group(1) if m_small else '?'}MB, 쌓는 답안: {mem[0]['detail'][:36]}…)" if mem else "(행 없음)")

    # h16: 수백 줄 뒤에만 틀리는 답안. 무작위 입력(3~60줄)으로는 못 잡고,
    # scale 을 받는 gen_big 으로 만든 중간 크기 입력(약 2천·2만 줄)을 독립 구현과 견주어 잡는다.
    d = copy_s1("h16_mid_size")
    src = (d / "s1.cpp").read_text(encoding="utf-8")
    late = "static long long g_late_lines = 0;\n"
    pos = src.index(marker)
    brace = src.index("{", src.index("getline", pos))
    src = (src[:pos] + late + src[pos:brace + 1]
           + " if (++g_late_lines == 501) std::cout << \"BAD\\n\";" + src[brace + 1:])
    (d / "s1.cpp").write_text(src, encoding="utf-8")
    rc, data, caught = verify(d, "--fuzz", "50", "--no-cov")
    mid = [r for r in data["rows"] if r["check"].startswith("중간 크기 비교")]
    row("h16 수백 줄 뒤에만 틀리는 답안", "FAIL, 중간 크기 비교가 잡는다",
        rc == 1 and bool(mid) and mid[0]["status"] == "FAIL",
        f"({data['verdict']}, 중간 크기 {mid[0]['status'] if mid else '행 없음'})")

    # h12: 받은 자료 정리. 워드, 압축, 메일에서 글과 첨부를 꺼낸다
    import zipfile
    inbox = OUT / "inbox_test"
    inbox.mkdir()
    doc = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>문제 1. 주문 접수</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>N</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>신규</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>')
    with zipfile.ZipFile(inbox / "problems.docx", "w") as z:
        z.writestr("word/document.xml", doc)
    with zipfile.ZipFile(inbox / "samples.zip", "w") as z:
        z.writestr("p1_sample.in", "N 1 B 5 10\n")
        z.writestr("../evil.txt", "x")
    (inbox / "mail.eml").write_bytes(
        b"Subject: exam\r\nFrom: a@example.com\r\nTo: b@example.com\r\nMIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=XX\r\n\r\n--XX\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Problem 3 is in the body.\r\n--XX\r\nContent-Type: text/plain\r\n"
        b"Content-Disposition: attachment; filename=p3.in\r\n\r\nA 1\r\n--XX--\r\n")
    (inbox / "old.hwp").write_bytes(b"\xd0\xcf\x11\xe0")
    # 윈도우에서 옮겨 온 파일: 따라온 Zone.Identifier 는 건너뛰고, 메모장의 UTF-16 글은 UTF-8 로 바꾼다
    (inbox / "old.hwp:Zone.Identifier").write_bytes(b"[ZoneTransfer]\r\nZoneId=3\r\n")
    (inbox / "note16.txt").write_bytes("문제 2 메모\r\n".encode("utf-16"))
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "inbox_scan.py")],
                       capture_output=True, text=True, env=dict(os.environ, COTEST_INBOX=str(inbox)))
    docx_txt = (inbox / "_text" / "problems.docx.txt")
    got_doc = docx_txt.exists() and "문제 1. 주문 접수" in docx_txt.read_text(encoding="utf-8") and "| N | 신규 |" in docx_txt.read_text(encoding="utf-8")
    got_zip = (inbox / "_unpacked" / "samples" / "p1_sample.in").exists() and not (inbox / "_unpacked" / "evil.txt").exists() and not (inbox / "evil.txt").exists()
    eml_txt = inbox / "_text" / "mail.eml.txt"
    got_eml = eml_txt.exists() and "Problem 3" in eml_txt.read_text(encoding="utf-8") and (inbox / "_unpacked" / "mail" / "p3.in").exists()
    scan = (inbox / "_SCAN.md").read_text(encoding="utf-8") if (inbox / "_SCAN.md").exists() else ""
    got_hwp = "old.hwp" in scan and "사람이 할 일" in scan
    u16 = inbox / "_text" / "note16.txt.utf8.txt"
    got_win = ("Zone.Identifier`" not in scan and "윈도우가 덧붙인 파일 1개" in scan
               and u16.exists() and "문제 2 메모" in u16.read_text(encoding="utf-8"))
    row("h12 받은 자료 정리", "워드·압축·메일을 풀고, 못 읽는 파일은 사람에게 넘긴다",
        p.returncode == 0 and got_doc and got_zip and got_eml and got_hwp and got_win,
        f"(워드 {got_doc}, 압축 {got_zip}, 메일 {got_eml}, 옛 한글 {got_hwp}, 윈도우 파일 {got_win})")

    # h13: 기대 출력이 다른 모델이 따로 구한 출력과 다르면 조건부. 원문 근거를 적어 가리면 풀린다.
    d = copy_s1("h13_xcheck_diff")
    xo = d / "xcheck" / "03_spike_edges.out"
    xo.write_bytes(xo.read_bytes() + b"EXTRA LINE\n")
    rc, data, _ = verify(d, "--fuzz", "200", "--no-cov")
    xr = [r for r in data["rows"] if r["check"].startswith("정답 사례 교차 확인")]
    diff_cond = data["verdict"] == "조건부" and bool(xr) and xr[0]["status"] == "확인" and "03_spike_edges" in xr[0]["detail"]
    (d / "xcheck" / "RESOLVED.md").write_text(
        "| 사례 | 맞는 쪽 | 원문 근거 |\n|---|---|---|\n| 03_spike_edges | 기대 출력 | 원문에 EXTRA LINE 이라는 출력은 없다 |\n",
        encoding="utf-8")
    rc, data, _ = verify(d, "--fuzz", "200", "--no-cov")
    row("h13 교차 확인 불일치", "조건부, 근거를 적으면 풀린다", diff_cond and data["verdict"] == "PASS",
        f"(불일치 때 조건부 {diff_cond}, 가린 뒤 {data['verdict']})")
    # 사례가 새로 생기거나 입력이 바뀌면 "아직 안 본 사례"로 센다
    (d / "tests" / "07_new.in").write_bytes(b"T A 100\n")
    (d / "tests" / "07_new.out").write_bytes(b"TICK A 100 OK\n")
    (d / "tests" / "01_example.in").write_bytes((d / "tests" / "01_example.in").read_bytes() + b"\n")
    import xcheck
    xs = xcheck.status(d)
    row("h13b 바뀐 사례", "새 사례와 입력이 바뀐 사례를 다시 볼 것으로 센다",
        set(xs["unchecked"]) == {"07_new", "01_example"}, f"({xs['unchecked']})")

    # h14: codex_ask.sh cases 가 입력만 넘기고(기대 출력과 답안은 주지 않는다) 받은 출력을 견준다
    d = copy_s1("h14_cases")
    shutil.rmtree(d / "xcheck")
    env = dict(os.environ, CODEX_BIN=str(fake), FAKE_RC="0", FAKE_XDIR=str(d / "tests"))
    p = subprocess.run(["bash", str(ROOT / "scripts" / "codex_ask.sh"), "cases", str(d)],
                       capture_output=True, text=True, env=env)
    xs = xcheck.status(d)
    p2 = subprocess.run(["bash", str(ROOT / "scripts" / "codex_ask.sh"), "cases", str(d)],
                        capture_output=True, text=True, env=env)
    row("h14 교차 확인 호출", "입력만 넘기고, 받은 출력이 모두 같고, 두 번째 호출은 할 일이 없다",
        p.returncode == 0 and xs["ran"] and len(xs["match"]) == xs["total"] and "새로 확인할" in p2.stdout,
        f"(rc {p.returncode}, 일치 {len(xs['match'])}/{xs['total']})")
    for f in (ROOT / "logs").glob("codex_cases_s1_*.log"):
        f.unlink()

    print()
    print("하네스 자체 시험: " + ("통과" if ok else "실패"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
