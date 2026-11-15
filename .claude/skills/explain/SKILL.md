---
name: explain
description: 제출한 코드의 설명서(EXPLAIN.md)를 쓴다. 사용자가 답안을 스스로 설명할 수 있게 한다. 제출 뒤에 쓴다. 인자는 문제 이름(예 p1).
---

# 코드 설명서 쓰기

문제: $ARGUMENTS

읽는 사람은 파이썬에 익숙하다. 아래 C++ 문법은 따로 설명하지 않아도 된다.
`struct`, 함수, 참조(`&`, `const&`), `enum class`, `switch`, `unordered_map` 의 `find`·`contains`, 반복자(`it->second`), `long long`, `getline` 과 `istringstream`.
그 밖의 문법(`string_view`, `from_chars`, 구조적 바인딩, `constexpr`, 이름 없는 `namespace`, `std::map` 의 비교 함수 등)은 처음 보는 것으로 다룬다.

## 쓰는 법
1. `problems/pN/` 의 `pN.cpp`, `PROBLEM.md`, `DECISIONS.md`, `REPORT.md` 를 읽는다.
2. `EXPLAIN.md` 를 `templates/FORMATS.md` 의 형식으로 쓴다.
3. 지킬 것
   - 코드에 있는 것만 설명한다. 없는 기능을 지어내지 않는다.
   - 문법 설명은 "파이썬의 무엇과 비슷한가"로 시작하면 좋다.
   - "예제 따라가기"는 실제로 프로그램을 돌려 출력을 확인하고 쓴다.
   - "예상 질문과 답"에는 약점을 묻는 질문도 넣는다(어디가 느린가, 어떤 입력에서 깨질 수 있나, AI가 쓴 부분을 어떻게 믿었나). 답은 정직하게 쓴다.
   - "직접 해 볼 것"은 10분 안에 끝나는 작은 수정으로 한다(한도 값 바꾸기, 거부 이유 하나 추가하기 등). `scripts/verify.sh` 로 스스로 확인하는 법을 함께 적는다.
4. `scripts/log_step.sh "<모델>" "pN 설명서 작성 (제출 뒤)"`
