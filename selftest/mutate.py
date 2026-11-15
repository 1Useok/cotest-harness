"""일부러 버그를 넣는다. 하네스가 버그를 잡는지 시험하는 데 쓴다.

각 항목: 이름 -> (설명, 원래 코드, 바꾼 코드). 원래 코드가 정확히 한 번 나와야 한다.
"""
import sys

MUTANTS = {
    "m1_off_by_one": (
        "3번째가 아니라 4번째 급변 시세에서 SHIFT",
        "if (s.spike_count < SHIFT_COUNT) return TickResult::Spike;",
        "if (s.spike_count <= SHIFT_COUNT) return TickResult::Spike;",
    ),
    "m2_overflow": (
        "시세 가격 상한 검사가 빠져 큰 수에서 곱셈이 넘친다",
        "!parse_int(f[2], price) || price < 1 || price > MAX_PRICE) {",
        "!parse_int(f[2], price) || price < 1) {",
    ),
    "m3_trailing_garbage": (
        "숫자 뒤의 쓰레기 글자를 통과시킨다 (10.5 를 10 으로 읽음)",
        "return ec == std::errc{} && ptr == last;",
        "return ec == std::errc{};",
    ),
    "m4_fill_after_cancel": (
        "취소된 주문에 체결을 반영한다",
        "if (o.status != Status::Live) {",
        "if (o.status == Status::Filled) {",
    ),
    "m5_overfill": (
        "남은 수량보다 많은 체결을 받아들인다",
        "if (qty > leaves) {",
        "if (false && qty > leaves) {",
    ),
    "m6_extra_fields": (
        "필드가 남아도 통과시킨다",
        "if (f.size() != 3 || !parse_int(f[1], id) || !parse_int(f[2], qty)) {",
        "if (f.size() < 3 || !parse_int(f[1], id) || !parse_int(f[2], qty)) {",
    ),
    "m7_narrowing": (
        "주문 금액을 int 에 담아 큰 값이 잘린다",
        "if (price * qty > MAX_NOTIONAL) return Reject::NotionalLimit;",
        "const int notional = price * qty; if (notional > MAX_NOTIONAL) return Reject::NotionalLimit;",
    ),
    "m8_check_order": (
        "검사 순서가 바뀜 (중복 번호보다 매매구분을 먼저 본다)",
        "if (orders.contains(id)) return Reject::DupId;\n    if (side != \"B\" && side != \"S\") return Reject::BadSide;",
        "if (side != \"B\" && side != \"S\") return Reject::BadSide;\n    if (orders.contains(id)) return Reject::DupId;",
    ),
}


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--list":
        for name, (desc, _, _) in MUTANTS.items():
            print(f"{name}\t{desc}")
        return
    src, name, dst = sys.argv[1:4]
    _, old, new = MUTANTS[name]
    text = open(src, encoding="utf-8").read()
    if text.count(old) != 1:
        sys.exit(f"{name}: 바꿀 코드가 {text.count(old)}번 나온다 (1번이어야 한다)")
    open(dst, "w", encoding="utf-8").write(text.replace(old, new))


if __name__ == "__main__":
    main()
