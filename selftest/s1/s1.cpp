// s1: 시세 필터, 주문 검증, 체결 반영 (하네스 자체 시험용 예제)
// 가정: 없음. PROBLEM.md 가 모든 규칙을 정한다.
// 예외 처리 방침: 형식이 틀린 줄은 BAD, 규칙에 걸린 주문·취소·체결은 REJECT <번호> <이유>.
//                어느 쪽도 상태를 바꾸지 않고 다음 줄을 계속 처리한다.
// 시간 복잡도: 줄 하나당 종목 조회 O(log 종목 수), 주문 조회 평균 O(1).
// 실전이라면 더 바꿀 것: 종목을 정수 번호로 바꿔 배열로 조회, 주문 저장 공간을 미리 확보.
#include <charconv>
#include <cstddef>
#include <iostream>
#include <map>
#include <string>
#include <string_view>
#include <system_error>
#include <unordered_map>
#include <vector>

namespace {

constexpr long long MAX_PRICE = 1'000'000'000;
constexpr long long MAX_QTY = 1'000;
constexpr long long MAX_NOTIONAL = 100'000'000;
constexpr std::size_t MAX_SYMBOL_LEN = 12;
constexpr int SHIFT_COUNT = 3;   // 비슷한 급변 시세가 이 횟수만큼 이어지면 기준가를 옮긴다

struct SymbolState {
    long long last = 0;        // 기준가. 0이면 아직 시세가 없다
    long long candidate = 0;   // 급변 시세의 후보가. 0이면 후보가 없다
    int spike_count = 0;
    long long net = 0;         // 매수 체결 합 - 매도 체결 합
    bool traded = false;
};

enum class Status { Live, Filled, Canceled };

struct Order {
    std::string symbol;
    char side = 'B';
    long long qty = 0;
    long long cum = 0;         // 누적 체결 수량
    Status status = Status::Live;
};

enum class TickResult { Ok, Spike, Shift };

enum class Reject {
    None, BadId, DupId, BadSide, BadQty, QtyLimit, BadPrice,
    NotionalLimit, NoMarketData, PriceBand, UnknownId, NotActive, Overfill
};

// std::less<> 를 쓰면 string_view 로 바로 찾을 수 있다(임시 string 을 만들지 않는다).
// std::map 은 이름순으로 정렬돼 있어 마지막 POS 출력에 그대로 쓴다.
using SymbolMap = std::map<std::string, SymbolState, std::less<>>;
using OrderMap = std::unordered_map<long long, Order>;

const char* to_text(TickResult r) {
    switch (r) {
        case TickResult::Ok: return "OK";
        case TickResult::Spike: return "SPIKE";
        case TickResult::Shift: return "SHIFT";
    }
    return "?";
}

const char* to_text(Reject r) {
    switch (r) {
        case Reject::None: return "NONE";
        case Reject::BadId: return "BAD_ID";
        case Reject::DupId: return "DUP_ID";
        case Reject::BadSide: return "BAD_SIDE";
        case Reject::BadQty: return "BAD_QTY";
        case Reject::QtyLimit: return "QTY_LIMIT";
        case Reject::BadPrice: return "BAD_PRICE";
        case Reject::NotionalLimit: return "NOTIONAL_LIMIT";
        case Reject::NoMarketData: return "NO_MARKET_DATA";
        case Reject::PriceBand: return "PRICE_BAND";
        case Reject::UnknownId: return "UNKNOWN_ID";
        case Reject::NotActive: return "NOT_ACTIVE";
        case Reject::Overfill: return "OVERFILL";
    }
    return "?";
}

// 줄을 스페이스와 탭으로 나눈다. 글자를 복사하지 않고 원래 줄을 가리킨다.
void split_fields(std::string_view line, std::vector<std::string_view>& out) {
    out.clear();
    std::size_t i = 0;
    while (i < line.size()) {
        while (i < line.size() && (line[i] == ' ' || line[i] == '\t')) ++i;
        if (i >= line.size()) break;
        const std::size_t start = i;
        while (i < line.size() && line[i] != ' ' && line[i] != '\t') ++i;
        out.push_back(line.substr(start, i - start));
    }
}

// 글자 전체가 정수일 때만 true. "10.5", "12abc", "+5", "", 64비트를 넘는 수는 false.
bool parse_int(std::string_view s, long long& value) {
    const char* first = s.data();
    const char* last = first + s.size();
    const auto [ptr, ec] = std::from_chars(first, last, value);
    return ec == std::errc{} && ptr == last;
}

// |price - base| 가 base 의 10%를 넘는가. 두 값 모두 MAX_PRICE 이하라 곱셈이 넘치지 않는다.
bool is_far(long long price, long long base) {
    const long long diff = price > base ? price - base : base - price;
    return diff * 10 > base;
}

TickResult apply_tick(SymbolState& s, long long price) {
    if (s.last == 0 || !is_far(price, s.last)) {
        s.last = price;
        s.candidate = 0;
        s.spike_count = 0;
        return TickResult::Ok;
    }
    if (s.candidate == 0 || is_far(price, s.candidate)) {
        s.candidate = price;
        s.spike_count = 1;
        return TickResult::Spike;
    }
    ++s.spike_count;
    if (s.spike_count < SHIFT_COUNT) return TickResult::Spike;
    s.last = price;
    s.candidate = 0;
    s.spike_count = 0;
    return TickResult::Shift;
}

void print_reject(long long id, Reject reason) {
    std::cout << "REJECT " << id << ' ' << to_text(reason) << '\n';
}

void handle_tick(const std::vector<std::string_view>& f, SymbolMap& symbols) {
    long long price = 0;
    if (f.size() != 3 || f[1].size() > MAX_SYMBOL_LEN ||
        !parse_int(f[2], price) || price < 1 || price > MAX_PRICE) {
        std::cout << "BAD\n";
        return;
    }
    auto it = symbols.find(f[1]);
    if (it == symbols.end()) it = symbols.emplace(std::string(f[1]), SymbolState{}).first;
    const TickResult result = apply_tick(it->second, price);
    std::cout << "TICK " << f[1] << ' ' << price << ' ' << to_text(result) << '\n';
}

// 검사 순서는 문제의 표와 같다.
Reject check_new(long long id, std::string_view symbol, std::string_view side,
                 long long price, long long qty,
                 const SymbolMap& symbols, const OrderMap& orders) {
    if (id < 1) return Reject::BadId;
    if (orders.contains(id)) return Reject::DupId;
    if (side != "B" && side != "S") return Reject::BadSide;
    if (qty < 1) return Reject::BadQty;
    if (qty > MAX_QTY) return Reject::QtyLimit;
    if (price < 1 || price > MAX_PRICE) return Reject::BadPrice;
    // 위에서 두 값의 상한을 검사했으므로 곱이 최대 10^12 이라 넘치지 않는다.
    if (price * qty > MAX_NOTIONAL) return Reject::NotionalLimit;
    const auto it = symbols.find(symbol);
    if (it == symbols.end()) return Reject::NoMarketData;
    if (is_far(price, it->second.last)) return Reject::PriceBand;
    return Reject::None;
}

void handle_new(const std::vector<std::string_view>& f, const SymbolMap& symbols, OrderMap& orders) {
    long long id = 0;
    long long price = 0;
    long long qty = 0;
    if (f.size() != 6 || f[2].size() > MAX_SYMBOL_LEN ||
        !parse_int(f[1], id) || !parse_int(f[4], price) || !parse_int(f[5], qty)) {
        std::cout << "BAD\n";
        return;
    }
    const Reject reason = check_new(id, f[2], f[3], price, qty, symbols, orders);
    if (reason != Reject::None) {
        print_reject(id, reason);
        return;
    }
    Order order;
    order.symbol = std::string(f[2]);
    order.side = f[3][0];
    order.qty = qty;
    orders.emplace(id, std::move(order));
    std::cout << "ACCEPT " << id << '\n';
}

void handle_cancel(const std::vector<std::string_view>& f, OrderMap& orders) {
    long long id = 0;
    if (f.size() != 2 || !parse_int(f[1], id)) {
        std::cout << "BAD\n";
        return;
    }
    const auto it = orders.find(id);
    if (it == orders.end()) {
        print_reject(id, Reject::UnknownId);
        return;
    }
    if (it->second.status != Status::Live) {
        print_reject(id, Reject::NotActive);
        return;
    }
    it->second.status = Status::Canceled;
    std::cout << "CANCELED " << id << '\n';
}

void handle_fill(const std::vector<std::string_view>& f, SymbolMap& symbols, OrderMap& orders) {
    long long id = 0;
    long long qty = 0;
    if (f.size() != 3 || !parse_int(f[1], id) || !parse_int(f[2], qty)) {
        std::cout << "BAD\n";
        return;
    }
    const auto it = orders.find(id);
    if (it == orders.end()) {
        print_reject(id, Reject::UnknownId);
        return;
    }
    Order& o = it->second;
    if (qty < 1) {
        print_reject(id, Reject::BadQty);
        return;
    }
    if (o.status != Status::Live) {
        print_reject(id, Reject::NotActive);
        return;
    }
    const long long leaves = o.qty - o.cum;
    if (qty > leaves) {
        print_reject(id, Reject::Overfill);
        return;
    }
    o.cum += qty;
    if (o.cum == o.qty) o.status = Status::Filled;

    // 접수할 때 시세가 있던 종목이므로 반드시 찾는다.
    SymbolState& s = symbols.find(o.symbol)->second;
    s.net += (o.side == 'B') ? qty : -qty;
    s.traded = true;
    std::cout << "FILL " << id << ' ' << o.cum << ' ' << (o.qty - o.cum) << '\n';
}

}  // namespace

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    SymbolMap symbols;
    OrderMap orders;
    std::vector<std::string_view> fields;
    fields.reserve(8);

    std::string line;
    while (std::getline(std::cin, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        split_fields(line, fields);
        if (fields.empty()) continue;

        const std::string_view type = fields[0];
        if (type == "T") handle_tick(fields, symbols);
        else if (type == "N") handle_new(fields, symbols, orders);
        else if (type == "C") handle_cancel(fields, orders);
        else if (type == "F") handle_fill(fields, symbols, orders);
        else std::cout << "BAD\n";
    }

    for (const auto& [name, s] : symbols) {
        if (s.traded) std::cout << "POS " << name << ' ' << s.net << '\n';
    }
    return 0;
}
