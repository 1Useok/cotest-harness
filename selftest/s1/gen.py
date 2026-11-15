"""s1 입력 생성기 (3층).

gen(rng) 은 입력 전체를 문자열로 돌려준다. rng 는 random.Random 이다.
정상 입력, 경계값, 쓰레기 입력을 섞는다.
"""
SYMS = ["A", "B7", "005930"]
MAX_PRICE = 1_000_000_000


def rand_id(rng, max_id):
    r = rng.random()
    if r < 0.90:
        return rng.randint(1, max_id)
    return rng.choice([0, -1, 99, max_id + 1])


def tick(rng, sym, base, spike):
    r = rng.random()
    b = base[sym]
    if r < 0.50:                                   # 기준가 근처
        price = b + rng.randint(-b // 12, b // 12)
        base[sym] = max(1, min(price, MAX_PRICE))
    elif r < 0.60:                                 # 정확히 10% 경계와 그 바로 옆
        price = b + rng.choice([-1, 1]) * (b // 10) + rng.choice([-1, 0, 1])
    elif r < 0.85 and sym in spike:                # 직전 급변 수준을 반복 (SHIFT 를 만든다)
        s = spike[sym]
        price = s + rng.randint(-s // 12, s // 12)
    else:                                          # 새 급변
        price = int(b * rng.choice([0.5, 0.7, 0.85, 1.15, 1.3, 1.6]))
        spike[sym] = max(1, price)
    if rng.random() < 0.03:
        price = rng.choice([0, -5, MAX_PRICE, MAX_PRICE + 1])
    return f"T {sym} {price}"


def new_order(rng, sym, base, max_id):
    oid = rand_id(rng, max_id)
    side = rng.choice(["B", "S"]) if rng.random() < 0.93 else rng.choice(["X", "b", "BS", "0"])
    b = base[sym]
    r = rng.random()
    if r < 0.70:
        price = b + rng.randint(-b // 8, b // 8)   # 가격 범위 안팎
    elif r < 0.85:
        price = b + rng.choice([-1, 1]) * (b // 10) + rng.choice([-1, 0, 1])
    else:
        price = rng.choice([0, -1, 1, MAX_PRICE, MAX_PRICE + 1, 100_000, 100_001])
    qty = rng.choice([1, 2, 3, 5, 8, 10, 20, 20, 100, 1000, 1000, 1001, 0, -3, 5000])
    return f"N {oid} {sym} {side} {price} {qty}"


def garbage(rng, sym):
    return rng.choice([
        f"T {sym}", f"T {sym} 10.5", f"T {sym} abc", f"T {sym} 100 200", "T",
        f"T {sym} +100", f"T {sym} 007", f"T {sym} --5", f"T {sym} -", f"T {sym} 1e3",
        f"T {sym} 9223372036854775807", f"T {sym} 9223372036854775808",
        f"T {sym} -9223372036854775809", f"T {sym} 99999999999999999999",
        "T ABCDEFGHIJKLM 5", "T ABCDEFGHIJKL 5", f"t {sym} 5", f"TT {sym} 5",
        f"N 1 {sym} B 100", f"N 1 {sym} B 100 10 extra", f"N 1 {sym} B 1e3 10",
        f"N one {sym} B 100 10", f"N 007 {sym} B 0100 01", f"N 1 {sym} B 100 10.0",
        f"N 2 {sym} B 99999999999999999999 1", f"N 2 {sym} S 100 99999999999999999999",
        f"N 99999999999999999999 {sym} S 100 1", "N 3 ABCDEFGHIJKLM B 100 1",
        "C", "C 1 2", "C x", "C 1.0", "C 99999999999999999999",
        "F 1", "F 1 1 1", "F 1 x", "F x 1", "F 1 99999999999999999999", "F 1 1.5",
        "Q 1", "", "   ", "\t", "HELLO", "1 2 3",
    ])


def decorate(rng, line):
    r = rng.random()
    if r < 0.06:
        line = line.replace(" ", "\t")
    elif r < 0.12:
        line = line.replace(" ", "  ")
    elif r < 0.16:
        line = "  " + line + " \t"
    if rng.random() < 0.05:
        line += "\r"
    return line


def gen(rng):
    base = {s: rng.choice([50, 1000, 70000, 100000, 999_999_999]) for s in SYMS}
    spike = {}
    max_id = rng.choice([3, 6, 12])
    lines = []
    for _ in range(rng.randint(3, 60)):
        sym = rng.choice(SYMS)
        r = rng.random()
        if r < 0.30:
            lines.append(tick(rng, sym, base, spike))
        elif r < 0.58:
            lines.append(new_order(rng, sym, base, max_id))
        elif r < 0.68:
            lines.append(f"C {rand_id(rng, max_id)}")
        elif r < 0.90:
            qty = rng.choice([1, 1, 2, 3, 5, 10, 20, 100, 1000, 0, -1])
            lines.append(f"F {rand_id(rng, max_id)} {qty}")
        else:
            lines.append(garbage(rng, sym))
    text = "\n".join(decorate(rng, ln) for ln in lines)
    return text + ("\n" if rng.random() < 0.9 else "")


BIG = 200_000


def gen_big(rng, scale=1.0):
    """실행 시간을 재는 큰 입력 (20만 줄). scale 을 주면 같은 모양으로 줄 수만 그 배율로 줄인다
    (verify 가 성장률과 중간 크기 비교에 쓴다)."""
    n = max(1, int(BIG * scale))
    base = {s: 70000 for s in SYMS}
    spike = {}
    lines = []
    for i in range(n):
        sym = rng.choice(SYMS)
        r = rng.random()
        if r < 0.4:
            lines.append(tick(rng, sym, base, spike))
        elif r < 0.8:
            lines.append(f"N {i + 1} {sym} B {base[sym]} 10")
        else:
            lines.append(f"F {rng.randint(1, i + 1)} 1")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import random
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    sys.stdout.write(gen(random.Random(seed)))
