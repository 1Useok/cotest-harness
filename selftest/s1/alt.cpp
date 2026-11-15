#include <algorithm>
#include <charconv>
#include <cstdint>
#include <iostream>
#include <map>
#include <string>
#include <system_error>
#include <vector>

using Integer = std::int64_t;

bool parse_integer(const std::string& text, Integer& value) {
    std::size_t start = !text.empty() && text[0] == '-' ? 1 : 0;
    if (start == text.size()) return false;
    for (std::size_t i = start; i < text.size(); ++i) {
        if (text[i] < '0' || text[i] > '9') return false;
    }
    auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size();
}

std::vector<std::string> split(const std::string& line) {
    std::vector<std::string> fields;
    std::size_t start = line.find_first_not_of(" \t");
    while (start != std::string::npos) {
        std::size_t end = line.find_first_of(" \t", start);
        if (end == std::string::npos) {
            fields.push_back(line.substr(start));
            break;
        }
        fields.push_back(line.substr(start, end - start));
        start = line.find_first_not_of(" \t", end);
    }
    return fields;
}

bool far_from(Integer price, Integer reference) {
    Integer difference = price >= reference ? price - reference : reference - price;
    return difference * 10 > reference;
}

struct Market {
    Integer reference = 0;
    Integer candidate = 0;
    int count = 0;
};

struct Order {
    std::string symbol;
    bool buy;
    Integer filled;
    Integer remaining;
    bool canceled;
};

// Nonnegative decimal arithmetic keeps total positions exact for any input length.
void add_quantity(std::string& total, int quantity) {
    std::size_t i = total.size();
    int carry = quantity;
    while (i > 0 && carry > 0) {
        --i;
        carry += total[i] - '0';
        total[i] = static_cast<char>('0' + carry % 10);
        carry /= 10;
    }
    if (carry > 0) total = std::to_string(carry) + total;
}

std::string difference(const std::string& bought, const std::string& sold) {
    if (bought == sold) return "0";
    bool negative = bought.size() != sold.size()
        ? bought.size() < sold.size() : bought < sold;
    std::string larger = negative ? sold : bought;
    const std::string& smaller = negative ? bought : sold;
    std::size_t j = smaller.size();
    int borrow = 0;
    for (std::size_t i = larger.size(); i > 0;) {
        --i;
        int digit = larger[i] - '0' - borrow;
        if (j > 0) digit -= smaller[--j] - '0';
        borrow = digit < 0 ? 1 : 0;
        if (digit < 0) digit += 10;
        larger[i] = static_cast<char>('0' + digit);
    }
    larger.erase(0, larger.find_first_not_of('0'));
    return negative ? "-" + larger : larger;
}

struct Position {
    std::string bought = "0";
    std::string sold = "0";
};

struct ByteLess {
    bool operator()(const std::string& a, const std::string& b) const {
        return std::lexicographical_compare(a.begin(), a.end(), b.begin(), b.end(),
            [](unsigned char x, unsigned char y) { return x < y; });
    }
};

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::map<std::string, Market> markets;
    std::map<Integer, Order> orders;
    std::map<std::string, Position, ByteLess> positions;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        auto fields = split(line);
        if (fields.empty()) continue;

        const std::string& kind = fields[0];
        Integer id = 0, price = 0, quantity = 0;
        bool valid = false;
        if (kind == "T") {
            valid = fields.size() == 3 && fields[1].size() <= 12
                && parse_integer(fields[2], price)
                && price >= 1 && price <= 1000000000;
        } else if (kind == "N") {
            valid = fields.size() == 6 && fields[2].size() <= 12
                && parse_integer(fields[1], id)
                && parse_integer(fields[4], price)
                && parse_integer(fields[5], quantity);
        } else if (kind == "C") {
            valid = fields.size() == 2 && parse_integer(fields[1], id);
        } else if (kind == "F") {
            valid = fields.size() == 3 && parse_integer(fields[1], id)
                && parse_integer(fields[2], quantity);
        }
        if (!valid) {
            std::cout << "BAD\n";
            continue;
        }

        if (kind == "T") {
            const std::string& symbol = fields[1];
            Market& market = markets[symbol];
            std::string result;
            if (market.reference == 0 || !far_from(price, market.reference)) {
                market.reference = price;
                market.candidate = 0;
                market.count = 0;
                result = "OK";
            } else {
                if (market.count == 0 || far_from(price, market.candidate)) {
                    market.candidate = price;
                    market.count = 1;
                } else {
                    ++market.count;
                }
                result = "SPIKE";
                if (market.count == 3) {
                    market.reference = price;
                    market.candidate = 0;
                    market.count = 0;
                    result = "SHIFT";
                }
            }
            std::cout << "TICK " << symbol << ' ' << price << ' ' << result << '\n';
        } else if (kind == "N") {
            const std::string& symbol = fields[2];
            const std::string& side = fields[3];
            auto market = markets.find(symbol);
            std::string reason;
            if (id < 1) reason = "BAD_ID";
            else if (orders.find(id) != orders.end()) reason = "DUP_ID";
            else if (side != "B" && side != "S") reason = "BAD_SIDE";
            else if (quantity < 1) reason = "BAD_QTY";
            else if (quantity > 1000) reason = "QTY_LIMIT";
            else if (price < 1 || price > 1000000000) reason = "BAD_PRICE";
            else if (price * quantity > 100000000) reason = "NOTIONAL_LIMIT";
            else if (market == markets.end()) reason = "NO_MARKET_DATA";
            else if (far_from(price, market->second.reference)) reason = "PRICE_BAND";
            if (reason.empty()) {
                orders.emplace(id, Order{symbol, side == "B", 0, quantity, false});
                std::cout << "ACCEPT " << id << '\n';
            } else {
                std::cout << "REJECT " << id << ' ' << reason << '\n';
            }
        } else {
            auto found = orders.find(id);
            std::string reason;
            if (found == orders.end()) reason = "UNKNOWN_ID";
            else if (kind == "F" && quantity < 1) reason = "BAD_QTY";
            else if (found->second.canceled || found->second.remaining == 0)
                reason = "NOT_ACTIVE";
            else if (kind == "F" && quantity > found->second.remaining)
                reason = "OVERFILL";

            if (!reason.empty()) {
                std::cout << "REJECT " << id << ' ' << reason << '\n';
                continue;
            }
            Order& order = found->second;
            if (kind == "C") {
                order.canceled = true;
                std::cout << "CANCELED " << id << '\n';
            } else {
                order.filled += quantity;
                order.remaining -= quantity;
                Position& position = positions[order.symbol];
                add_quantity(order.buy ? position.bought : position.sold,
                             static_cast<int>(quantity));
                std::cout << "FILL " << id << ' ' << order.filled
                          << ' ' << order.remaining << '\n';
            }
        }
    }
    for (const auto& [symbol, position] : positions) {
        std::cout << "POS " << symbol << ' '
                  << difference(position.bought, position.sold) << '\n';
    }
}
