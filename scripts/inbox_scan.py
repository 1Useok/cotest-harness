#!/usr/bin/env python3
"""받은 과제 자료를 정리한다(전처리). inbox/ 에 받은 그대로 넣어 두고 돌린다.

사용: scripts/inbox_scan.sh

하는 일
- 압축 파일(.zip, .tar, .tar.gz, .tgz)을 inbox/_unpacked/<이름>/ 에 푼다. .7z, .rar 등은 풀지 못한다고 적는다.
- 같은 이름에 다른 내용이 겹치면 덮어쓰지 않고 이름에 __2, __3 을 붙인 뒤 _SCAN.md 에 적는다.
- 메일 파일(.eml)의 본문을 inbox/_text/ 에 글로 꺼내고 첨부를 inbox/_unpacked/<이름>/ 에 꺼낸다.
- 워드(.docx), 한글(.hwpx), 웹 문서(.html) 의 글을 inbox/_text/<이름>.txt 로 꺼낸다. 표는 칸을 ` | ` 로 잇는다.
- 메모장이 UTF-16 이나 cp949 로 저장한 글은 UTF-8 로 바꿔 inbox/_text/<이름>.utf8.txt 에 둔다.
- 윈도우가 덧붙이는 파일(<이름>:Zone.Identifier, desktop.ini, Thumbs.db)은 건너뛰고 개수만 적는다.
- 모든 파일을 종류, 크기, 읽는 방법과 함께 inbox/_SCAN.md 에 적는다.

하지 않는 일
- 원본은 고치지도 지우지도 않는다.
- PDF 와 그림(.png, .jpg)은 바꾸지 않는다. AI가 Read 도구로 직접 읽는다.
- 옛 한글(.hwp), 옛 워드(.doc), 엑셀(.xls)은 꺼내지 못한다. 사람이 PDF 로 저장하거나 본문을 붙여 넣어야 한다.
- 문제를 나누거나 분류하지 않는다. 그것은 /intake 가 한다.
"""
import email
import email.policy
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
INBOX = Path(os.environ.get("COTEST_INBOX") or (ROOT / "inbox"))   # 자체 시험에서만 바꾼다
TEXT = INBOX / "_text"
UNPACK = INBOX / "_unpacked"
MAX_UNZIP_BYTES = 200 * 1024 * 1024
TEXT_EXT = {".txt", ".md", ".in", ".out", ".csv", ".tsv", ".json", ".cpp", ".h", ".hpp", ".py", ".log", ".dat", ".ans", ".exp"}

notes = []
skipped = []   # 윈도우가 덧붙이는 파일(건너뛴 것)
written = {}   # 이번에 쓴 파일 → 내용의 sha256
renamed = []   # 이름이 겹쳐 따로 둔 파일: (원래 이름, 실제로 둔 곳)
ARCHIVE_EXT = (".zip", ".tar", ".tar.gz", ".tgz")
UNKNOWN_ARCHIVE_EXT = (".7z", ".rar", ".egg", ".alz", ".gz", ".bz2", ".xz", ".cab", ".lzh")


def put(target, data):
    """파일을 쓴다. 이번에 이미 다른 내용을 쓴 이름이면 덮어쓰지 않고 __2, __3 을 붙인다.
    같은 내용이면 그대로 둔다(다시 돌려도 파일이 늘지 않는다). 실제로 쓴 경로를 돌려준다."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    h = hashlib.sha256(data).hexdigest()
    cand, k = target, 1
    while written.get(cand, h) != h:
        k += 1
        head, dot, rest = target.name.partition(".")
        cand = target.with_name(f"{head}__{k}{dot}{rest}")
    if cand != target:
        renamed.append((target, cand))
    cand.parent.mkdir(parents=True, exist_ok=True)
    if not (cand.is_file() and cand.read_bytes() == data):
        cand.write_bytes(data)
    written[cand] = h
    return cand


def archive_stem(path):
    """압축 이름에서 확장자를 뗀다(자료.tar.gz → 자료)"""
    low = path.name.lower()
    for ext in (".tar.gz", ".tgz", ".tar", ".zip"):
        if low.endswith(ext):
            return path.name[: -len(ext)] or "archive"
    return path.stem


def windows_junk(name):
    """윈도우 탐색기로 복사할 때 따라오는 파일: <이름>:Zone.Identifier, desktop.ini, Thumbs.db"""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    return base.endswith(":Zone.Identifier") or base.lower() in ("desktop.ini", "thumbs.db")


def shown(path):
    """보여 줄 경로. 작업 폴더 안이면 그 기준으로 적는다."""
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def safe_name(name):
    return re.sub(r"[^\w.\-가-힣]+", "_", name).strip("_") or "file"


def unzip(path, dest):
    """압축을 푼다. 폴더 밖으로 나가는 경로와 너무 큰 압축은 거부한다."""
    out = []
    try:
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIP_BYTES:
                notes.append(f"{path.name}: 풀면 200MB 를 넘어 풀지 않았다")
                return out
            for info in z.infolist():
                if info.is_dir():
                    continue
                if windows_junk(info.filename):
                    skipped.append(f"{path.name}/{info.filename}")
                    continue
                # 한글 파일 이름이 깨져 있으면 되살린다(윈도우에서 만든 zip)
                name = info.filename
                if not info.flag_bits & 0x800:
                    try:
                        name = name.encode("cp437").decode("cp949")
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        pass
                # 윈도우(PowerShell 의 Compress-Archive 등)가 만든 zip 은 폴더 구분자가 역슬래시다
                name = name.replace("\\", "/")
                if name.endswith("/"):
                    continue
                target = (dest / name).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    notes.append(f"{path.name}: 수상한 경로라 건너뜀: {info.filename}")
                    continue
                out.append(put(target, z.read(info)))
    except (zipfile.BadZipFile, OSError) as e:
        notes.append(f"{path.name}: 압축을 풀지 못했다 ({e})")
    return out


def untar(path, dest):
    """tar, tar.gz, tgz 를 푼다. zip 과 같은 한도. 폴더 밖 경로는 거부하고, 링크·장치 파일은 건너뛴다."""
    out = []
    try:
        with tarfile.open(path, "r:*") as t:
            members = t.getmembers()
            if sum(m.size for m in members if m.isfile()) > MAX_UNZIP_BYTES:
                notes.append(f"{path.name}: 풀면 200MB 를 넘어 풀지 않았다")
                return out
            for m in members:
                if m.isdir():
                    continue
                if not m.isfile():
                    notes.append(f"{path.name}: 보통 파일이 아니라(링크·장치 파일) 건너뜀: {m.name}")
                    continue
                if windows_junk(m.name):
                    skipped.append(f"{path.name}/{m.name}")
                    continue
                target = (dest / m.name).resolve()
                if not str(target).startswith(str(dest.resolve()) + os.sep):
                    notes.append(f"{path.name}: 수상한 경로라 건너뜀: {m.name}")
                    continue
                f = t.extractfile(m)
                out.append(put(target, f.read() if f else b""))
    except (tarfile.TarError, OSError, EOFError) as e:
        notes.append(f"{path.name}: 압축을 풀지 못했다 ({e})")
    return out


def docx_text(path, counts=None):
    """워드 문서의 문단과 표를 순서대로 글로 꺼낸다.
    수식은 그 안의 글자만 `[수식: …]` 로, 그림은 `[그림: 꺼내지 못함]` 으로 그 자리에 둔다(counts 에 개수를 센다)."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    mns = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
    fallback = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(ns + "body")
    lines = []
    counts = {} if counts is None else counts
    seen = set()   # 표 칸의 문단을 두 번 볼 때 두 번 세지 않게

    def para_text(p):
        parts = []

        def walk(node, in_fallback=False):
            if node.tag == mns + "oMath":
                parts.append("[수식: " + "".join(t.text or "" for t in node.iter(mns + "t")) + "]")
                if id(node) not in seen:
                    seen.add(id(node))
                    counts["math"] = counts.get("math", 0) + 1
                return
            if node.tag in (ns + "drawing", ns + "pict") and not in_fallback:
                parts.append("[그림: 꺼내지 못함]")
                if id(node) not in seen:
                    seen.add(id(node))
                    counts["pic"] = counts.get("pic", 0) + 1
            if node.tag == ns + "t":
                parts.append(node.text or "")
            elif node.tag == ns + "tab":
                parts.append("\t")
            elif node.tag in (ns + "br", ns + "cr"):
                parts.append("\n")
            for c in node:
                walk(c, in_fallback or node.tag == fallback)

        walk(p)
        return "".join(parts)

    for child in body if body is not None else []:
        if child.tag == ns + "p":
            lines.append(para_text(child))
        elif child.tag == ns + "tbl":
            for row in child.iter(ns + "tr"):
                cells = []
                for cell in row.findall(ns + "tc"):
                    cells.append(" ".join(para_text(p) for p in cell.iter(ns + "p")).strip())
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
    return "\n".join(lines) + "\n"


def hwpx_text(path, counts=None):
    """한글(hwpx) 문서의 글을 꺼낸다. 표의 모양은 잃을 수 있다.
    수식(hp:equation)은 수식 글(script)을 `[수식: …]` 로, 그림(hp:pic)은 `[그림: 꺼내지 못함]` 으로 둔다."""
    chunks = []
    counts = {} if counts is None else counts
    seen = set()
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n))
        for n in names:
            root = ET.fromstring(z.read(n))
            for p in root.iter():
                if p.tag.endswith("}p"):
                    parts = []
                    for t in p.iter():
                        if t.tag.endswith("}t"):
                            parts.append(t.text or "")
                        elif t.tag.endswith("}equation") or t.tag.endswith("}pic"):
                            eq = t.tag.endswith("}equation")
                            if eq:
                                parts.append("[수식: " + "".join(s.text or "" for s in t.iter() if s.tag.endswith("}script")).strip() + "]")
                            else:
                                parts.append("[그림: 꺼내지 못함]")
                            if id(t) not in seen:
                                seen.add(id(t))
                                key = "math" if eq else "pic"
                                counts[key] = counts.get(key, 0) + 1
                    chunks.append("".join(parts))
    return "\n".join(chunks) + "\n"


def html_text(raw):
    raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", raw)
    raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


def eml_extract(path):
    """메일의 본문을 글로, 첨부를 파일로 꺼낸다."""
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    head = [f"{k}: {msg.get(k, '')}" for k in ("Subject", "From", "To", "Date")]
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        text = body.get_content()
        if body.get_content_type() == "text/html":
            text = html_text(text)
    files = []
    dest = UNPACK / safe_name(path.stem)
    for part in msg.iter_attachments():
        name = safe_name(part.get_filename() or "attachment")
        data = part.get_payload(decode=True) or b""
        files.append(put(dest / name, data))
    return "\n".join(head) + "\n\n" + text + "\n", files


def looks_text(path):
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return False
    if chunk.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True   # UTF-16 (메모장의 유니코드 저장)
    if b"\0" in chunk:
        return False
    for enc in ("utf-8", "cp949"):
        try:
            chunk.decode(enc)
            return True
        except UnicodeDecodeError:
            continue
    return False


def handle(path, rows, depth=0):
    rel = path.relative_to(INBOX)
    ext = path.suffix.lower()
    size = path.stat().st_size
    kind, how = "기타", "AI가 열어 보고 판단한다"
    low = path.name.lower()
    try:
        if low.endswith(ARCHIVE_EXT):
            dname = safe_name(archive_stem(path))
            dest = UNPACK / dname
            if depth >= 2:
                inner = []
            elif ext == ".zip":
                inner = unzip(path, dest)
            else:
                inner = untar(path, dest)
            kind, how = "압축", f"`inbox/_unpacked/{dname}/` 에 {len(inner)}개를 풀었다"
            rows.append((rel, kind, size, how))
            for f in sorted(set(inner)):
                handle(f, rows, depth + 1)
            return
        if low.endswith(UNKNOWN_ARCHIVE_EXT):
            kind, how = "압축(못 푼다)", "**풀지 못하는 압축이다. 사람이 윈도우에서 풀어 다시 넣는다**"
            notes.append(f"**{rel}: 풀지 못하는 압축이다. 사람이 윈도우에서 풀어 다시 넣는다**")
            rows.append((rel, kind, size, how))
            return
        if ext == ".eml":
            text, files = eml_extract(path)
            out = put(TEXT / (safe_name(path.stem) + ".eml.txt"), text)
            kind, how = "메일", f"본문 → `{shown(out)}`, 첨부 {len(files)}개를 꺼냈다"
            rows.append((rel, kind, size, how))
            for f in sorted(files):
                handle(f, rows, depth + 1)
            return
        if ext in (".docx", ".hwpx"):
            counts = {}
            text = docx_text(path, counts) if ext == ".docx" else hwpx_text(path, counts)
            out = put(TEXT / (safe_name(path.stem) + ext + ".txt"), text)
            if ext == ".docx":
                kind, how = "워드", f"글 → `{shown(out)}` (그림 속 글자와 수식은 빠진다. 옮겨 적은 뒤 `scripts/transcribe_check.sh` 로 견준다)"
            else:
                kind, how = "한글(hwpx)", f"글 → `{shown(out)}` (표의 모양은 잃을 수 있다. 옮겨 적은 뒤 `scripts/transcribe_check.sh` 로 견준다)"
            if counts:
                msg = (f"수식 {counts.get('math', 0)}개, 그림 {counts.get('pic', 0)}개를 글로 온전히 꺼내지 못했다. "
                       "이 파일을 PDF 로 저장해 inbox/ 에 넣어 달라고 한다")
                how += f". **{msg}** (꺼낸 글의 `[수식: …]`, `[그림: 꺼내지 못함]` 자리)"
                notes.append(f"**{rel}: {msg}**")
        elif ext in (".html", ".htm"):
            raw = path.read_bytes()
            try:
                s = raw.decode("utf-8")
            except UnicodeDecodeError:
                s = raw.decode("cp949", "replace")
            out = put(TEXT / (safe_name(path.stem) + ".html.txt"), html_text(s))
            kind, how = "웹 문서", f"글 → `{shown(out)}`"
        elif ext == ".pdf":
            kind = "PDF"
            how = ("AI가 Read 도구로 직접 읽는다(쪽 범위를 준다). 글을 기계로 꺼내지 못했으니, 옮겨 적은 뒤 "
                   "두 번째 읽기와 견준다(`scripts/transcribe_check.sh`)")
            exe = shutil.which("pdftotext")
            if exe:
                out = TEXT / (safe_name(path.stem) + ".pdf.txt")
                part = TEXT / (safe_name(path.stem) + ".pdf.part")
                part.unlink(missing_ok=True)
                r = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), str(part)],
                                   capture_output=True, text=True, timeout=60)
                if part.exists():
                    data = part.read_bytes()
                    part.unlink()
                    out = put(out, data)
                if r.returncode == 0 and out.exists() and out.read_text(encoding="utf-8", errors="replace").strip():
                    how = (f"글 → `{shown(out)}` (pdftotext). AI는 Read 도구로도 직접 읽고, 옮겨 적은 글을 "
                           "이 글과 견준다(`scripts/transcribe_check.sh`). 스캔한 그림 PDF 면 글이 비어 있다")
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            kind, how = "그림", "AI가 Read 도구로 직접 본다. 옮겨 적은 뒤 두 번째 읽기와 견준다(`scripts/transcribe_check.sh`)"
        elif ext in (".hwp", ".doc", ".xls", ".ppt"):
            kind, how = "옛 형식", "**꺼내지 못한다.** 사람이 PDF 로 저장해 inbox/ 에 넣거나 본문을 대화에 붙여 넣는다"
            notes.append(f"{rel}: 사람이 PDF 로 저장하거나 본문을 붙여 넣어야 한다")
        elif ext in (".xlsx", ".pptx"):
            kind, how = "엑셀·발표 자료", "꺼내지 않았다. 필요하면 사람이 CSV 나 PDF 로 저장한다"
            notes.append(f"{rel}: 내용이 필요하면 사람이 CSV 나 PDF 로 저장한다")
        elif ext in TEXT_EXT or looks_text(path):
            raw = path.read_bytes()
            enc, conv = "utf-8", None   # conv: UTF-8 로 바꿔 _text/ 에 둘 글
            if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                enc, conv = "UTF-16 (메모장의 유니코드 저장)", raw.decode("utf-16")
            else:
                try:
                    raw.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        enc, conv = "cp949 (한글 윈도우 인코딩)", raw.decode("cp949")
                    except UnicodeDecodeError:
                        enc = "알 수 없음(글자가 깨질 수 있다)"
                        notes.append(f"{rel}: 인코딩을 알 수 없다. 사람이 원본을 열어 확인한다")
            flags = []
            if raw.startswith(b"\xef\xbb\xbf"):
                flags.append("맨 앞에 BOM")
            if b"\r\n" in raw or (conv is not None and "\r\n" in conv):
                flags.append("줄 끝 \\r\\n")
            kind = "글"
            how = f"그대로 읽는다. 인코딩 {enc}"
            if conv is not None:
                out = put(TEXT / (safe_name(path.name) + ".utf8.txt"), conv.lstrip("﻿"))
                how = f"UTF-8 로 바꾼 글 → `{shown(out)}` 를 읽는다. 원본 인코딩 {enc}"
            how += (", " + ", ".join(flags) if flags else "")
        else:
            notes.append(f"{rel}: 모르는 형식이다")
    except Exception as e:  # noqa: BLE001
        how = f"**꺼내다 실패했다**: {e}. 사람이 PDF 로 저장하거나 본문을 붙여 넣는다"
        notes.append(f"{rel}: 꺼내다 실패 ({e})")
    rows.append((rel, kind, size, how))


def main():
    INBOX.mkdir(exist_ok=True)
    TEXT.mkdir(exist_ok=True)
    rows = []
    top = sorted(p for p in INBOX.rglob("*") if p.is_file()
                 and "_text" not in p.relative_to(INBOX).parts
                 and "_unpacked" not in p.relative_to(INBOX).parts
                 and p.name not in ("_SCAN.md", "INDEX.md"))
    skipped.extend(str(p.relative_to(INBOX)) for p in top if windows_junk(p.name))
    top = [p for p in top if not windows_junk(p.name)]
    for p in top:
        handle(p, rows)
    lines = ["# 받은 자료 훑어보기 (scripts/inbox_scan.sh 가 만든다)", "",
             f"파일 {len(rows)}개. 원본은 그대로 두었다.", "",
             "| 파일 | 종류 | 크기(바이트) | 읽는 방법 |", "|---|---|---|---|"]
    for rel, kind, size, how in rows:
        lines.append(f"| `{rel}` | {kind} | {size} | {how} |")
    if renamed:
        lines += ["", f"이름이 겹쳐 따로 둔 파일 {len(renamed)}개 (내용이 달라 덮어쓰지 않고 이름에 `__2` 등을 붙였다):"]
        lines += [f"- `{shown(a)}` → `{shown(b)}`" for a, b in renamed]
    if notes:
        lines += ["", "## 사람이 할 일"] + [f"- {n}" for n in notes]
    if skipped:
        lines += ["", f"윈도우가 덧붙인 파일 {len(skipped)}개(Zone.Identifier, desktop.ini, Thumbs.db)는 건너뛰었다."]
    (INBOX / "_SCAN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if not rows:
        print("\ninbox/ 가 비어 있습니다. 받은 파일을 넣거나 문제를 대화에 붙여 넣으세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
