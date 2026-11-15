// 가정: (문제에 없어서 정한 것. DECISIONS.md 의 번호와 함께 적는다)
// 예외 처리 방침: (잘못된 줄을 어떻게 하는가. 예: BAD 를 출력하고 다음 줄을 계속 처리한다)
// 시간 복잡도: (메시지 하나당)
// 실전이라면 더 바꿀 것: (예: 종목을 정수 번호로 바꿔 배열로 조회)
#include <charconv>
#include <cstddef>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

// 줄을 스페이스와 탭으로 나눈다(여러 개가 이어져도 구분 하나, 줄 앞뒤 공백은 버린다: DECISIONS 의 D0).
// 글자를 복사하지 않고 원래 줄을 가리킨다. 공백이 자료인 문제(고정 폭 전문)에는 쓰지 않는다.
// 구분 문자가 다르면(쉼표, | 등) 이 함수를 문제에 맞게 고친다.
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

// 글자 전체가 정수일 때만 true.
// "10.5", "12abc", "+5", "", 64비트를 넘는 수는 false. "-3" 과 "007" 은 true.
bool parse_int(std::string_view s, long long& value) {
    const char* first = s.data();
    const char* last = first + s.size();
    const auto [ptr, ec] = std::from_chars(first, last, value);
    return ec == std::errc{} && ptr == last;
}

}  // namespace

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::vector<std::string_view> fields;
    fields.reserve(16);

    std::string line;
    while (std::getline(std::cin, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();   // 윈도우 줄바꿈
        split_fields(line, fields);
        if (fields.empty()) continue;   // 빈 줄. 문제가 다르게 정하면 고친다

        // 메시지 종류별로 처리한다. 한 줄이 잘못돼도 다음 줄은 계속 처리한다.
        long long unused = 0;
        (void)parse_int(fields[0], unused);
    }
    return 0;
}
