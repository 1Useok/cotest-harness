"""s1 불변식 검사기 (2층).

check(inp, out) 은 위반한 규칙의 목록을 돌려준다. 빈 목록이면 통과다.
정답을 다시 계산하지 않는다. 어떤 입력에서도 깨지면 안 되는 규칙만 본다.
"""
import re

LINE_RE = re.compile(
    r"^(BAD"
    r"|TICK \S+ [1-9]\d* (OK|SPIKE|SHIFT)"
    r"|ACCEPT [1-9]\d*"
    r"|REJECT (0|-?[1-9]\d*) [A-Z_]+"
    r"|CANCELED [1-9]\d*"
    r"|FILL [1-9]\d* [1-9]\d* (0|[1-9]\d*)"
    r"|POS \S+ (0|-?[1-9]\d*))$"
)


def fields_of(line):
    if line.endswith("\r"):
        line = line[:-1]
    return [x for x in re.split(r"[ \t]+", line) if x]


def check(inp, out):
    bad = []
    if out and not out.endswith("\n"):
        bad.append("출력이 줄바꿈으로 끝나지 않는다")
    out_lines = out.split("\n")
    if out_lines and out_lines[-1] == "":
        out_lines.pop()

    for i, ln in enumerate(out_lines):
        if not LINE_RE.match(ln):
            bad.append(f"출력 {i + 1}번째 줄의 형식이 틀리다: [{ln}]")
    if bad:
        return bad

    msgs = [f for f in (fields_of(ln) for ln in inp.split("\n")) if f]
    n_pos = 0
    while n_pos < len(out_lines) and out_lines[len(out_lines) - 1 - n_pos].startswith("POS "):
        n_pos += 1
    body, pos = out_lines[:len(out_lines) - n_pos], out_lines[len(out_lines) - n_pos:]
    if any(ln.startswith("POS ") for ln in body):
        bad.append("POS 줄이 다른 출력 사이에 섞여 있다")
    if len(body) != len(msgs):
        bad.append(f"메시지는 {len(msgs)}개인데 출력은 {len(body)}줄이다")
        return bad

    orders = {}   # 주문번호 -> [종목, 매매구분, 주문 수량, 누적 체결, 상태]
    net = {}
    for f, ln in zip(msgs, body):
        o = ln.split(" ")
        kind = o[0]
        if kind == "TICK":
            if f[0] != "T" or len(f) != 3 or o[1] != f[1]:
                bad.append(f"시세가 아닌 입력에 TICK 을 출력했다: {ln}")
        elif kind == "ACCEPT":
            oid = int(o[1])
            if f[0] != "N" or len(f) != 6:
                bad.append(f"신규 주문이 아닌 입력에 ACCEPT 를 출력했다: {ln}")
                continue
            if oid in orders:
                bad.append(f"주문번호 {oid} 를 두 번 접수했다")
            if f[3] not in ("B", "S"):
                bad.append(f"매매구분이 틀린 주문 {oid} 를 접수했다")
            qty = int(f[5])
            if not 1 <= qty <= 1000:
                bad.append(f"수량 {qty} 인 주문 {oid} 를 접수했다")
            orders[oid] = [f[2], f[3], qty, 0, "LIVE"]
        elif kind == "CANCELED":
            oid = int(o[1])
            if oid not in orders:
                bad.append(f"접수된 적 없는 주문 {oid} 를 취소했다")
            elif orders[oid][4] != "LIVE":
                bad.append(f"끝난 주문 {oid} 를 다시 취소했다")
            else:
                orders[oid][4] = "CANCELED"
        elif kind == "FILL":
            oid, cum, leaves = int(o[1]), int(o[2]), int(o[3])
            if oid not in orders:
                bad.append(f"접수된 적 없는 주문 {oid} 에 체결을 반영했다")
                continue
            sym, side, qty, prev, status = orders[oid]
            if status != "LIVE":
                bad.append(f"끝난 주문 {oid} ({status}) 에 체결을 반영했다")
            if cum <= prev:
                bad.append(f"주문 {oid} 의 누적 체결 수량이 늘지 않았다")
            if cum + leaves != qty:
                bad.append(f"주문 {oid}: 누적 {cum} + 남은 {leaves} 이 주문 수량 {qty} 과 다르다")
            if cum > qty:
                bad.append(f"주문 {oid}: 주문 수량 {qty} 보다 많이 체결됐다")
            delta = cum - prev
            net[sym] = net.get(sym, 0) + (delta if side == "B" else -delta)
            orders[oid][3] = cum
            if cum >= qty:
                orders[oid][4] = "FILLED"
        elif kind == "REJECT":
            if f[0] == "T":
                bad.append(f"시세 입력에 REJECT 를 출력했다: {ln}")

    names = [ln.split(" ")[1] for ln in pos]
    if names != sorted(names) or len(set(names)) != len(names):
        bad.append("POS 줄이 종목 순서대로가 아니거나 같은 종목이 두 번 나온다")
    if set(names) != set(net):
        bad.append(f"POS 에 나온 종목 {sorted(names)} 과 체결이 있었던 종목 {sorted(net)} 이 다르다")
    for ln in pos:
        _, sym, value = ln.split(" ")
        if sym in net and int(value) != net[sym]:
            bad.append(f"POS {sym}: 출력은 {value}, FILL 줄을 합치면 {net[sym]}")
    return bad


if __name__ == "__main__":
    import sys
    problems = check(open(sys.argv[1], encoding="utf-8", newline="").read(),
                     open(sys.argv[2], encoding="utf-8", newline="").read())
    print("\n".join(problems) if problems else "OK")
    sys.exit(1 if problems else 0)
