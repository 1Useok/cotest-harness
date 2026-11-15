> 공개본 주: 날짜와 일부 출처 표현, 사용자 경로와 세션 번호를 가렸다. 상황을 드러내는 낱말은 과제, 평가, 실전 같은 말로 바꿨다. 그 밖의 내용은 그대로다.

# 하네스 최종 점검 보고서 (GEMINI)
- 검토자: Antigravity, Gemini 4 Argon, High
- 시각: 2026-11-14 22:36 \~ 22:58 (한국 시각), 대상 커밋: 7861d1c
- 방식: 명령을 직접 돌리고 코드를 확인함. 복사본 경로: `/tmp/qa_GEMINI` (검토 종료 후 삭제 완료)

## 1. 결론 (5줄 이하)
- **조건부 준비됨.** 5층 교차 검증(`verify.py`)과 자체 점검(`selftest.py`)의 기본 골격은 단단하지만, 150분 실전에서 점수를 크게 잃거나 제출이 꼬일 수 있는 치명적 경로가 남아 있다.
- 가장 위험한 것은 ① **원문에 없는 거부 이유 글자를 AI가 지어내어(`REJ <번호> <지어낸 이유>`) 글자 단위 평가에서 통째로 오답이 되는 규칙(`AGENTS.md:49`)**, ② **교차 확인 불일치(`RESOLVED.md`)·미확인 사례·미실행 코드가 있어도 `조건부`가 아닌 `PASS`가 나오는 판정 구멍(`scripts/verify.py:508,920,943`)**, ③ **여러 문제 창을 동시에 돌릴 때 `log_step.sh`의 `git add -A`와 `collect_logs.py`의 폴더 삭제(`rmtree`)가 충돌해 작업 파일과 로그를 망가뜨리는 동시 실행 경합**이다.
- 작업 시작 전 아래 **즉시 고칠 상위 발견(F1\~F6)**만이라도 `AGENTS.md`, `prompts/`, `scripts/verify.py`, `scripts/mutants.py`, `scripts/log_step.sh`에서 고치고 들어가길 권한다.

## 2. 발견 (심각한 것부터, 15개 이하)

| # | 심각도 | 분류 | 위치 (`파일:줄`) | 한 줄 요약 | 실전에서 잃는 것 | 고치는 시간 |
|---|---|---|---|---|---|---|
| F1 | 치명 | 정의안됨 | `AGENTS.md:39,47-53`, `templates/FORMATS.md:97`, `prompts/alt.md:15` | 지어낸 거부 이유 글자 출력 지시 및 추천 기준(2·3번)의 내부 모순·프롬프트 누락 | 평가기와 글자가 달라 오답(대량 감점) | 10분 |
| F2 | 치명 | 검증구멍 | `scripts/verify.py:495-509,920,938-945`, `scripts/xcheck.py:67` | `RESOLVED.md` 임의 해명·교차 확인 누락(50% 미만)·미실행 줄·변형 0개가 모두 `PASS`로 통과 | 틀린 답안·기대 출력이 사람 확인 없이 제출됨 | 10분 |
| F3 | 치명 | 검증구멍 | `scripts/verify.py:76,444,726,868`, `templates/gen.py:13` | 정답 비교(`alt`), 불변식(`check.py`), 메모리 검사(`ASan/UBSan`)가 60줄 이하 입력에서만 돌아감 | 60줄 넘어 터지는 버그·오버플로가 `PASS`로 통과 | 10분 |
| F4 | 치명 | 실행오류 | `scripts/log_step.sh:36-42`, `scripts/collect_logs.py:403`, `.claude/settings.json:7` | 병렬 풀이 시 `git add -A`와 `shutil.rmtree("logs/raw/...")`가 잠금 없이 충돌 | 다른 문제 반쪽 코드 커밋, Git 잠금 실패, 로그 유실 | 10분 |
| F5 | 높음 | 검증구멍 | `scripts/mutants.py:30,67-75` | C++ 숫자 구분자(`1'000`)를 문자 상수로 오인해 파일 전체 변형 자리를 0곳으로 셈 | 변형 시험이 0/0 `PASS`로 무력화됨 | 5분 |
| F6 | 높음 | 실행오류 | `scripts/transcribe_check.py:24` | 한 글자 대문자(`B`,`S`,`A`,`F`,`C`,`K`,`W`,`N`), 부등호, 음수 부호, 한글(`이상`/`초과`) 누락 | 문제를 잘못 옮겨 적어도 `PASS` 출력 | 10분 |
| F7 | 높음 | 정의안됨 | `knowledge/TRAPS.md:32,37,223,283,286`, `templates/check.py:29` | 가격 예외(없는·이상한 가격 처리)에서 `갈림` 누락 및 나눗셈 먼저 권고 등 함정 사전 오류 | 카드 없이 한쪽만 구현해 평가 기준과 어긋남 | 10분 |
| F8 | 중간 | 검증구멍 | `scripts/verify.py:301-335,512-535` | `EDGE.md` 표가 비어도 `PASS`, `"사람 답 대기"` 문구를 미결정으로 잡지 못함 | 예외 사례 누락·미결정이 `PASS`로 통과 | 5분 |
| F9 | 높음 | 제출위험 | `AI_USAGE.md:9`, `logs/GIT_LOG.txt`, `logs/MANIFEST.md:14`, `scripts/collect_logs.py:397` | 제출 문서(`Fable 5.2`)와 원본 로그(`claude-opus-5-5`)의 모델 이름 불일치 및 `~/.codex` 전체 수집 | 모델 허위 기재 오해 및 과제 외 대화 유출 | 10분 |
| F10 | 중간 | 사람판단 | `templates/FORMATS.md:88-107`, `problems/p1/DECISIONS.md:20` | 결정 카드에 "원문 문장 인용"과 "작은 입력→출력 비교 예"가 없어 사람이 1분 안에 고르기 어려움 | 잘못된 선택지 결정 또는 판단 시간 지체 | 5분 |
| F11 | 중간 | 실행오류 | `scripts/inbox_scan.py:158,192-211` | 같은 이름 첨부파일 덮어쓰기 및 `.tar.gz`/`.7z` 미지원 | 받은 문제 자료 일부가 조용히 덮어써짐 | 5분 |
| F12 | 낮음 | 시간낭비 | `scripts/board.py:75-99`, `AGENTS.md:74`, `templates/AI_USAGE.md:12`, `scripts/collect_logs.py:436` | 현황판 대기 시간(`wait`) 0분 집계, `/ask` 문서 누락, 옛 모델 이름·`/export` 안내 잔존 | 시간 배분 착오 및 실전 직전 혼란 | 5분 |

### F1. 원문에 없는 거부 이유 글자를 지어내게 한 규칙과 추천 기준(2·3번)의 내부 모순
- **근거**: `AGENTS.md:39,47-53`, `templates/FORMATS.md:97`, `knowledge/TRAPS.md:101-102,120`, `templates/check.py:29`, `prompts/alt.md:15`
- **문제**:
  1. `AGENTS.md:49`는 원문에 `REJ <번호> <이유>` 형식이 있으면 원문에 없는 예외도 **`REJ <번호> <지어낸 이유>`로 표준 출력에 찍으라**고 지시한다. 그러나 `SUBMIT_RULES.md:9`처럼 평가는 글자 단위 비교다. 리허설 2 `p2`에서 AI가 지어낸 `REJ 1 PRICE`(`problems/p2/DECISIONS.md:18`)는 평가기의 `REJ … NOPRICE`와 글자가 달라 그대로 오답이 된다. 게다가 `AGENTS.md:39`와 `templates/FORMATS.md:97`은 "지어낸 오류 글자는 카드로 올리지 않는다"고 막아 사람조차 볼 수 없게 했다.
  2. `AGENTS.md:47`(추천 기준 2번)은 초과 체결(`overfill`)도 포지션에 반영하고 남은 수량을 음수나 0으로 찍으라고 추천하는데, 이는 `knowledge/TRAPS.md:101-102,120`(T38 "초과 체결을 먼저 검사", T39 "주문 수량 = 누적 체결 + 남은 수량", T43 "음수는 어느 쪽도 아니다") 및 `templates/check.py:29`("남은 수량은 0 이상")와 정면으로 충돌한다.
  3. `AGENTS.md:50`(추천 기준 3번)은 원문에 오류 줄 형식이 없으면 표준 출력은 그대로 두고(조용히 버리고) `stderr`에만 요약하라고 한다. 리허설 2 `p3`("살아 있는 번호 재사용")처럼 오류 줄 형식이 없는 문제에서는 표준 출력이 여전히 조용히 버려져 오답이 되며, 평가기가 `stderr`가 비어 있지 않다고 오답 처리할 위험까지 생긴다.
  4. 이 추천 기준 4가지는 `AGENTS.md`와 `prompts/ambig.md`에만 들어가고 **`prompts/alt.md`, `prompts/cases.md`, `prompts/review.md`에는 빠져 있다.**
- **고치는 법**:
  - `AGENTS.md:49`에서 새 이유 글자를 지어내지 못하게 막고, 원문에 이미 있는 이유 글자 가운데 가장 가까운 것을 쓰는 선택지와 원문 글자 그대로(통과/무시) 선택지를 결정 카드에 나란히 올리며 **문제를 낸 쪽에 질문할 문장(`/ask`)을 함께 적게** 바꾼다.
  - `AGENTS.md:50,64`의 `stderr` 출력은 환경 변수(`COTEST_DEBUG_STDERR=1`)가 있을 때만 내고 기본 제출 본에서는 끄며, `prompts/{alt,cases,review}.md`에도 같은 기준을 넣는다.

### F2. 교차 확인(`xcheck`) 불일치·누락, 미실행 줄, 변형 0개가 모두 `PASS`로 통과
- **근거**: `scripts/verify.py:224-233,495-509,920,938-945`, `scripts/xcheck.py:67-68`
- **문제**: `verify.py:224-233`의 `verdict()`는 표의 상태 칸이 `"확인"`이어도 `report.condition(...)`을 부르지 않으면 최종 판정을 **`PASS`**로 낸다.
  1. `scripts/verify.py:505-508`: 다른 모델의 정답(`xcheck/*.out`)이 기대 출력과 달라 AI가 `xcheck/RESOLVED.md`에 아무 8글자 이상 이유(`scripts/xcheck.py:67` `len(reason) >= 8`)를 적어 넣거나, `problems/p1/xcheck/RESOLVED.md:5-7`처럼 `"결정 D2 에 달림"`이라고 적어 두어도 `report.condition(...)`을 부르지 않아 **`PASS`**가 된다.
  2. `scripts/verify.py:502,505`: 새로 추가한 정답 사례의 절반 미만(예: 19개 중 9개)이 교차 확인을 전혀 안 거쳤거나(`unchecked`), 모든 사례가 80줄을 넘어 `can_check == 0`이어도 `report.condition(...)` 없이 **`PASS`**가 된다.
  3. `scripts/verify.py:920,938-945`: 실행되지 않은 코드 줄(`never_lines`)이 남아 있거나, 코드가 바뀐 뒤 변형 시험(`mutants.sh`)을 다시 안 돌렸거나(`m.get("sha") != sha`), 변형 자리가 0곳(`0/0 모두 잡음`)이어도 **`PASS`**가 된다.
- **고치는 법**: `scripts/verify.py:506`에서 `xs["unchecked"]`가 비어 있지 않거나 `RESOLVED.md`에 미확정 결정(`사람 답 대기`)이 걸려 있으면 `report.condition(...)`을 호출하고, `verify.py:920,939,944`에서 미실행 줄 존재·변형 시험 SHA 불일치·변형 대상 0개(`total == 0`)일 때도 `report.condition(...)`을 호출한다.

### F3. 큰 입력에서 독립 구현(`alt`)이 시간 초과로 건너뛰어져 대용량 전용 코드가 미검증으로 `PASS` 됨
- **근거**: `scripts/verify.py:76,444,726,816-824,895-900`, `problems/p2/VERIFY.txt:25,29`, `problems/p3/VERIFY.txt:25-27`, `problems/p3/p3.cpp:79-88,298-302`
- **문제**:
  1. `gen(rng)`과 `gen2(rng)`는 3\~60줄짜리 작은 입력만 만든다(`templates/gen.py:13`). 반면 50만\~100만 줄짜리 `big_inputs`에서는 `prompts/alt.md:20`이 `alt.cpp`를 느리게($O(N^2)$) 짜도 된다고 허용했기 때문에, 정작 중요한 큰 입력(`p1` 7개 중 4개, `p2` 9개 중 4개, `p3` 10개 중 9개)에서 `alt`가 12초 시간 초과로 멈춘다(`독립 구현은 시간 안에 못 끝내 비교 못 함`).
  2. `verify.py:896`에는 `# 시간은 쟀지만 출력이 맞는지는 견주지 못했다. PASS 로 덮지 않는다`라고 주석이 적혀 있지만, 실제로는 `report.condition(...)`을 부르지 않아(`verify.py:897`) **`p2/VERIFY.txt:29`처럼 그대로 `판정: PASS`가 나온다.** 또한 `big_inputs`에는 `check.py`도, `ASan/UBSan`(`san_bin`)도 돌리지 않는다.
  3. 그 결과 **작은 입력(60줄 이하)에서는 한 번도 실행되지 않고 큰 입력에서만 도는 코드**가 통째로 검증 사각지대에 빠진다. 실제로 `p3/VERIFY.txt:26-27`을 보면 해시 충돌 삭제(`p3.cpp:79-88`)와 1MB 출력 버퍼 비우기(`p3.cpp:299-300` `flush_if_big`, 만약 `cout.write` 없이 `out.clear()`만 해도 큰 입력 출력이 증발함)가 **미실행 줄 9줄 및 살아남은 변형 6개**로 남았는데도 `조건부` 사유에조차 들어가지 않았다.
  4. 복사본 `/tmp/qa_GEMINI`의 `p2.cpp:95`(`WindowQueue::pop_front`)에 `head_ >= 75`일 때 슬라이딩 윈도를 통째로 비우는 버그(`items_.clear()`)를 직접 심어 실험한 결과, 1층 정답 사례 22개·2층 `check.py`·3층 무작위 비교·`ASan/UBSan`을 **모두 `PASS`로 통과**하는 것을 확인했다.
- **고치는 법**: `verify.py`에 **`alt.cpp`와 `check.py`, `san_bin`이 시간 안에 끝나는 중간 크기(예: 1,000\~5,000줄, 해시 충돌·버퍼 비우기·큐 압축이 일어나는 크기) 입력 검사**를 추가하고, `alt_slow`가 있으면 자동으로 줄 수를 1/10로 줄인 입력에서 `alt`와 출력을 비교하며 실패 시 `report.condition(...)`을 호출한다.

### F4. 병렬 풀이 시 `log_step.sh`의 `git add -A`와 `collect_logs.py`의 폴더 삭제가 충돌
- **근거**: `scripts/log_step.sh:36-42`, `scripts/collect_logs.py:403`, `.claude/settings.json:7`
- **문제**:
  1. `scripts/log_step.sh:41`은 AI가 단계를 기록할 때마다 **`git add -A`로 저장소 전체를 스테이징해 커밋**한다. 안내문(`README.md:57`)대로 대화창 3개에서 `/solve p1`, `/solve p2`, `/solve p3`을 동시에 돌리면, `p1` 창이 기록할 때 `p2`·`p3` 창에서 수정 중인 미완성 코드와 테스트까지 한꺼번에 `p1` 커밋에 섞여 들어간다.
  2. `.claude/settings.json:7`의 `Stop` 훅은 매 응답 끝마다 `scripts/collect_logs.py --quiet`를 돌리는데, `collect_logs.py:403`은 잠금(`logs/.log_step.lock`) 없이 `shutil.rmtree("logs/raw/claude")`와 `shutil.rmtree("logs/raw/codex")`로 폴더를 지웠다 다시 만든다. 다른 창에서 `log_step.sh`가 `git add -A`를 돌리거나 `pack.sh`가 도는 순간 `logs/raw/` 파일이 사라져 Git 오류가 나거나 로그가 반쪽만 담길 수 있다.
- **고치는 법**: `scripts/log_step.sh:41`에서 문제 이름이 인자에 있으면 해당 문제 폴더와 로그 파일(`git add "problems/$prob" logs/ AI_USAGE.md`)만 스테이징하게 바꾸고, `collect_logs.py`도 `flock`으로 `logs/.log_step.lock`을 잡은 뒤 바뀐 파일만 덮어쓰게(`rmtree` 제거) 고친다.

### F5. `mutants.py`가 C++ 숫자 구분자(`1'000`)를 문자 상수로 오인해 변형 자리를 0곳으로 셈
- **근거**: `scripts/mutants.py:30,67-75`, `AI_USAGE.md:68,71`, `problems/p3/p3.cpp:34-36`
- **문제**: `scripts/mutants.py:67`의 `mask_code()`는 작은따옴표(`'`)를 무조건 문자 리터럴 시작으로 본다. C++14 숫자 구분자(예: `1'000`처럼 작은따옴표가 홀수 개)가 코드에 하나라도 들어가면 그 뒤부터 다음 `'`가 나올 때까지 파일 전체를 문자열로 지워 버린다. 리허설 2에서도 이 버그가 발생해(`AI_USAGE.md:68,71`) 답안에서 `'`를 손으로 지웠으나 정작 `mutants.py`는 고치지 않았다. 또한 `mutants.py:30`(`r" (<=|>=|==|!=|&&|\|\||<|>) "`)은 연산자 양옆에 공백이 없으면(`a<b`) 변형 자리를 찾지 못한다.
- **재현**: 복사본 `/tmp/qa_GEMINI`에서 `p2.cpp`의 `100;`을 `1'000 / 10;`으로 바꾸고 `python3 scripts/mutants.py p2` 실행 → `바꿀 수 있는 자리 0곳 중 0곳을 바꿔 보았다 / 변형 0개 중 0개를 잡았다` 출력, `verify.py`에서는 `변형 시험 | PASS | 0/0 모두 잡음` 출력 확인.
- **고치는 법**: `scripts/mutants.py:67`에서 `c == "'"`일 때 바로 앞 글자가 숫자나 영문자/밑줄(`i > 0 and src[i-1].isalnum()`)이면 숫자 구분자로 보고 건너뛰게 고친다.

### F6. `transcribe_check.py`가 한 글자 기호(`B`,`S`,`K`), 부등호, 한글(`이상`/`초과`), 순서 뒤바뀜을 못 잡음
- **근거**: `scripts/transcribe_check.py:24-27`
- **문제**: `TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?|[A-Z][A-Z0-9_]{1,}|<[^<>\n]{1,20}>")`는 **두 글자 이상 대문자**만 뽑고 집합(`set`)으로만 비교한다. 따라서 매수/매도(`B`/`S`), 통보 종류(`A`/`F`/`C`), 변수(`W`/`K`/`N`), 음수 부호(`-`), 부등호(`<`/`<=`), 한글 조건(`보다 크면` vs `이상이면`)이 바뀌거나, 두 숫자의 자리가 서로 바뀌어도 전혀 잡지 못한다.
- **재현**: `/tmp/qa_GEMINI/problems/p2/PROBLEM.md`에서 `매수(B)`를 `매수(S)`로, `보다 크면`을 `이상이면`으로, `보다 작으면`을 `이하이면`으로 바꾼 뒤 `python3 scripts/transcribe_check.py p2` 실행 → `다른 것이 없다 / 옮겨 적기 확인: 같다` (종료 코드 0) 출력 확인.
- **고치는 법**: 정규식에 한 글자 대문자(`\b[A-Z]\b`), 부호(`-?\d+`), 부등호(`<=|>=|<|>|≤|≥`), 핵심 한글 낱말(`이상|이하|초과|미만|보다 크|보다 작`)을 포함하고, 집합(`set`) 대신 **등장 순서 리스트(`difflib.SequenceMatcher`)나 개수(`Counter`)**로 비교한다.

### F7. 가격 예외(없는·이상한 가격 처리)에서 `TRAPS.md`의 `갈림` 누락 및 함정 사전 오류
- **근거**: `knowledge/TRAPS.md:32,37,223,283,286`, `templates/check.py:29`
- **문제**:
  1. 지침이 가장 무게를 두는 예외("신호나 판단에 쓸 가격이 없거나 이상할 때")와 직결되는 `TRAPS.md:32`(T1: 가격이 0·음수·NaN이면 이전 기준가 유지)와 `TRAPS.md:37`(T6: 튀는 틱은 버리고 이전 유효 틱 유지)에 **`갈림` 표시가 없다.** 실전에서는 이상한 틱이 오면 "이전 기준가 유지"가 아니라 "그 종목의 기준가를 무효로 만들고 다음 정상 틱까지 주문을 거부(막는다)"하는 문제를 자주 내는데, `갈림`이 없어 AI가 카드를 올리지 않고 한쪽만 구현할 위험이 크다.
  2. 또한 **체결 통보(`Fill`)의 가격이 0이거나 상한 밖일 때**(추천 기준 1번 "값이 이상하면 막는다" vs 2번 "체결 통보는 버리지 않는다"), **버린 이상 틱이 시각(`last_time`)이나 건수 창을 밀어내는지**도 `TRAPS.md`에 빠져 있다.
  3. `TRAPS.md:223`(T93)의 "곱하기 전에 나눗셈을 먼저"는 정수 나눗셈 버림 때문에 경계값 판정이 틀리므로(`p2` D2와 모순) 위험한 조언이고, `TRAPS.md:283,286`(T180 정정 수량 변경 불가 단정, T183 하한가 절사 `갈림` 누락) 및 `templates/check.py:29`("주문 수량 = 누적 체결 + 남은 수량", 취소된 주문에서 깨짐)도 부정확하다.
- **고치는 법**: `TRAPS.md` T1·T6·T183에 `갈림`을 붙이고 "이상한 틱이 오면 기준가를 무효(없음)로 바꿀지, 직전 기준가를 유지할지"와 "체결 통보의 가격이 범위 밖일 때"를 추가한다. T93에서 "나눗셈을 먼저" 문구를 지운다.

### F8. `EDGE.md` 표가 비어도 `PASS`, `"사람 답 대기"` 문구를 미결정으로 잡지 못함
- **근거**: `scripts/verify.py:301-335,512-535`, `problems/p1/EDGE.md:17-18`, `problems/p3/EDGE.md:13-14,22`
- **문제**:
  1. `scripts/verify.py:328`의 `parse_edge_md()`는 `E\d+`로 시작하는 행이 하나도 없으면 빈 리스트(`[]`)를 돌려주는데, `verify.py:514`는 `if rows is None:`만 검사해 행이 0개이면 **`PASS` (`0행 모두 테스트가 있다`)**로 통과시킨다.
  2. `verify.py:521`은 `EDGE.md`의 근거 칸에서 `"?"`와 `"미정"`만 검사하고, `templates/FORMATS.md:174`가 시키는 `"사람 답 대기"` 문구는 검사하지 않는다(실제로 `problems/p1/EDGE.md:17-18`과 `problems/p3/EDGE.md:13-14`에 `"사람 답 대기"`가 그대로 남아 있다). 또한テスト 파일 칸에 `"check.py"`라고만 적어 두어도(`verify.py:524`) 실제 `.in` 사례 없이 통과한다.
- **고치는 법**: `verify.py:514`에서 `not rows`일 때 `FAIL` 또는 `조건부`로 처리하고, `verify.py:521`에 `"사람 답 대기" in why` 검사를 추가한다.

### F9. 제출 문서(`Fable 5.2`)와 원본 로그(`claude-opus-5-5`)의 모델 이름 불일치 및 `~/.codex` 전체 수집
- **근거**: `AI_USAGE.md:9`, `logs/GIT_LOG.txt`, `logs/MANIFEST.md:14-19`, `logs/raw/claude/*.jsonl`, `scripts/collect_logs.py:394,397`
- **문제**:
  1. 리허설 2 원본 로그(`logs/raw/claude/*.jsonl`)를 직접 열어 확인한 결과, 6개 세션 모두 `requestedModel`과 `message.model`이 **`claude-opus-5-5`**였다(`logs/MANIFEST.md:14-19`와 `usage_export.py --check` 결과도 `claude-opus-5-5`). 그런데 AI가 손으로 적은 `AI_USAGE.md:9`와 모든 `log_step.sh` 커밋(`logs/GIT_LOG.txt`)에는 **`Claude Fable 5.2`**로 적혀 있다. 이미 열려 있던 창에서 설정만 바꿨거나 AI가 `.claude/settings.json`(`"model": "fable"`)을 보고 자기 모델 이름을 짐작해 적은 것이다. 제출 묶음(`submit.zip`) 안에서 요약 문서와 원본 로그의 모델 이름이 다르면 과제 규정 위반(허위 기재)으로 오해받을 수 있다.
  2. `scripts/collect_logs.py:397`은 `codex_root.rglob("*.jsonl")`에서 작업 시작 시각 이후 바뀐 **모든 Codex 세션**을 작업 폴더(`cwd`) 확인 없이 복사한다. 같은 컴퓨터의 다른 폴더에서 돌린 Codex 대화까지 제출 묶음에 들어간다.
- **고치는 법**: `scripts/log_step.sh`와 `scripts/pack.py`가 `.jsonl` 원본 로그에 실제로 찍힌 모델 이름을 읽어 `AI_USAGE.md`와 다른지 대조해 경고하게 하고, `collect_logs.py:397`은 Codex 세션의 `cwd`가 이 작업 폴더나 `/tmp/cotest_`일 때만 수집하게 제한한다.

### F10. 결정 카드가 사람이 1분 안에 고르기 어렵게 구성됨 (원문 문장·입출력 비교 예 누락)
- **근거**: `templates/FORMATS.md:88-107`, `problems/p1/DECISIONS.md:14-44`, `problems/p3/DECISIONS.md:14-42`
- **문제**: 지금 결정 카드(`templates/FORMATS.md:99-105`)는 `A (추천): ... / B (원문 그대로): ...`를 줄글로만 적는다. 사용자가 진행 중 1분 안에 결정하려면 ① **문제 원문의 어느 문장 때문에 갈리는지(원문 그대로 인용)**와 ② **3줄짜리 작은 입력에서 A와 B의 출력이 눈으로 어떻게 다른지**가 바로 보여야 하는데 두 가지가 모두 빠져 있다.
- **고치는 법**: 아래 **4절 질문 E**에 바로 복사해 쓸 수 있는 1분 결정 카드 양식을 제시했다.

### F11. `inbox_scan.py`가 같은 이름의 첨부파일·압축 안 파일을 조용히 덮어씀
- **근거**: `scripts/inbox_scan.py:158,192-211`
- **문제**: 메일(`.eml`) 첨부파일이나 여러 `.zip` 안에 파일 이름(`stem`)이 같은 파일(예: `p1/sample.in`, `p2/sample.in` 또는 두 메일의 `problem.pdf`)이 있으면 `inbox/_unpacked/<이름>`과 `inbox/_text/<stem>.pdf.txt`에 뒤 파일이 앞 파일을 경고 없이 덮어쓴다. 또한 `.tar.gz`나 `.7z` 압축은 풀지 못한다.
- **고치는 법**: `inbox_scan.py`에서 풀거나 변환할 때 상대 경로나 번호 접두사(`p1__sample.in`)를 붙여 이름 충돌을 막고, `shutil.unpack_archive`로 `.tar.gz`도 지원한다.

### F12. 현황판 대기 시간(`wait`) 0분 집계, `/ask` 문서 누락, 옛 안내 문구 잔존
- **근거**: `scripts/board.py:75-99`, `AGENTS.md:74`, `templates/AI_USAGE.md:12`, `scripts/collect_logs.py:436,462`, `problems/p1/REPORT.md:10,30`, `problems/p3/REPORT.md:13,18`
- **문제**:
  1. `.claude/skills/solve/SKILL.md:106`은 풀이가 끝나면 `clock.sh mark pN done`만 부르고 `wait`를 부르지 않아, `board.py:88`에서 사람 결정을 기다린 시간(`wait`)이 내내 `0분`으로 찍힌다.
  2. `AGENTS.md:74`의 스킬 목록에 새로 만든 `ask`가 빠져 있고, `templates/AI_USAGE.md:12`(`archive_run.sh:21`이 미리 복사함)에는 옛 모델 설명이 박혀 있으며, `collect_logs.py:436,462`는 더 이상 안 쓰는 `/export` 할 일을 출력한다. `p1/REPORT.md:30`과 `p3/REPORT.md:13,18`에도 결정 반영 전 문구가 남아 있다.
- **고치는 법**: `board.py`에서 미결정 카드가 있을 때 `wait` 상태로 표시하고, `AGENTS.md:74`, `templates/AI_USAGE.md:12`, `collect_logs.py:436`의 낡은 문구를 정리한다.

## 3. 추정 (근거를 대지 못한 걱정, 5개 이하)
- **U1**: 실전 환경의 VS Code 확장 버전이나 운영체제 설정에 따라 `Claude VSCode.log` 경로·시간대가 달라지면 `collect_logs.py:216`의 `/btw`(곁 질문) 시각 매칭이 누락될 수 있다(진행 중 `/btw`를 쓰지 않으면 영향 없음).
- **U2**: 문제를 낸 쪽이 C++20 표준 라이브러리의 부동소수점 출력이나 로케일·특수 문자 인코딩(EUC-KR 파일)을 섞어 주면 현재 UTF-8 고정 파서(`inbox_scan.py`)가 글자를 깨뜨릴 수 있다.

## 4. 질문별 답 (A \~ G, 질문마다 3줄 이하)
- **A (정의 안 된 동작과 결정 기준)**: `AGENTS.md:49`의 "지어낸 거부 이유 글자 출력"은 글자 단위 평가에서 가장 위험한 감점 요인이며, 추천 기준 2·3번은 `TRAPS.md`·`check.py`와 충돌하고 `prompts/{alt,cases,review}.md`에 빠져 있다(**F1**). 가장 무게를 두는 예외인 "가격이 없거나 이상할 때"도 `TRAPS.md` T1·T6에 `갈림`이 빠져 있어 카드로 올라오지 않는다(**F7**).
- **B (틀린 답이 PASS로 나가는 길)**: `verify.py`가 `xcheck/RESOLVED.md` 임의 해명, 교차 확인 50% 미만 누락, 미실행 코드 줄, 변형 0개(`1'000` 버그)를 모두 `조건부` 없이 `PASS`로 통과시킨다(**F2, F5, F8**). 또한 `alt` 비교·`check.py`·`ASan/UBSan`이 60줄 이하 입력에서만 돌아가, 60줄 뒤에만 터지는 버그를 넣었을 때 실제로 `PASS`가 나오는 것을 확인했다(**F3**).
- **C (실전에서 멈추거나 꼬이는 곳)**: 세 문제를 여러 창에서 동시에 풀 때 `log_step.sh`의 `git add -A`와 Stop 훅 `collect_logs.py`의 `rmtree`가 잠금 없이 충돌한다(**F4**). `transcribe_check.py`는 `B`/`S` 뒤바뀜과 `>`/`>=` 변경을 놓치며(**F6**), 매번 `verify.sh`를 돌릴 때 100만 줄 입력을 파이썬으로 다시 만들어 시간이 크게 끌린다.
- **D (AI 사용 내역 기록)**: 리허설 2 제출본에서 `AI_USAGE.md`·`GIT_LOG.txt`(`Claude Fable 5.2`)와 원본 `.jsonl`·`MANIFEST.md`(`claude-opus-5-5`)의 모델 이름이 서로 다르다(**F9**). 또한 `collect_logs.py`가 작업 폴더 밖의 `~/.codex` 대화까지 모두 수집한다(**F9**).
- **E (사람과의 호흡)**: 지금 결정 카드는 원문 문장 인용과 작은 입출력 비교가 없어 사람이 1분 안에 판단하기 어렵다(**F10**). `templates/FORMATS.md:99-105`를 아래 표 형식으로 바꾸길 권한다.

| 항목 | 내용 (1분 결정 카드 예시: `p2-D1`) |
|---|---|
| **원문 문장** | 처리 1: `"창 안의 체결가 가운데 가장 높은 값을 H, 가장 낮은 값을 L 이라 하자."` (체결가가 0개일 때의 규칙이 원문에 없음) |
| **작은 입력 예** | 첫 줄 `1000 10 2` 뒤 첫 메시지로 `O 0 1 A1 AAA B 100 1` (앞선 체결가 `T` 없음) |
| **선택지 비교** | **A (원문 그대로, +0분)**: 가격 점검을 건너뛰고 통과 → 출력 `ACK 1`<br>**B (기존 이유 글자 사용, +3분)**: 기준가가 없으므로 가격 거부 → 출력 `REJ 1 PRICE`<br>**C (문제를 낸 쪽에 질문, +1분)**: *"창 안에 체결가 T가 없을 때 주문 O는 통과(ACK)인가요, 거부인가요? 거부라면 이유 글자는 무엇인가요?"* |

- **F (직접 돌려 본 결과)**: `/tmp/qa_GEMINI`에서 `selftest.py --quick`(h1\~h15 전부 PASS), `mutants.py` 숫자 구분자 `1'000` 버그(변형 0곳), `transcribe_check.py` `B`/`S`·부등호 변경 미탐지, `usage_export.py --check`, `models.sh`, `p2.cpp` 슬라이딩 윈도 버그 주입 시 `verify.py` 통과를 모두 직접 실행해 재현했다.
- **G (과잉 설계와 복잡도)**: 검증 5층·교차 확인·자체 점검(`selftest.py`)은 과잉 설계가 아니며 그대로 유지해야 한다. 다만 진행 중에 `verify.sh`를 중간 실행할 때마다 100만 줄짜리 `gen_big`과 2배 크기 측정을 매번 다시 돌리는 것은 시간을 많이 잡아먹으므로 `--quick`(또는 `--no-big`) 옵션을 두는 것이 좋다.

## 5. 고치지 말아야 할 것
- **5층 검증 구조(`tests/`, `check.py`, `gen.py`+`alt.cpp`, `ASan/UBSan`, `gen_big`)와 `selftest.py`의 결함 주입 시험(h1\~h15)**: 실제 버그를 잡는 핵심 안전망이므로 줄이거나 빼지 않는다.
- **`scripts/codex_ask.sh`의 빈 임시 폴더 격리 실행**: 독립 구현(`alt.cpp`)과 정답 사례 교차 확인(`xcheck/`)이 답안을 보지 못하게 막는 가장 중요한 장치다.
- **`scripts/final_gate.sh`의 제출 직전 게이트**: 결정 미확정, 파일 해시 불일치, 조건부 승인 여부를 한 번에 막아 주는 마지막 보루다.

## 6. 직접 돌린 것
1. `cd /tmp/qa_GEMINI && timeout 300 python3 scripts/selftest.py --quick` → 종료 코드 0 (`올바른 답안: PASS`, `h1`\~`h15` 모두 예상대로 잡음).
2. `/tmp/qa_GEMINI/problems/p2/p2.cpp`에 `1'000` 숫자 구분자 넣은 뒤 `python3 scripts/mutants.py p2` 실행 → `바꿀 수 있는 자리 0곳 중 0곳을 바꿔 보았다` 재현(**F5**).
3. `/tmp/qa_GEMINI/problems/p2/PROBLEM.md`에서 `B`↔`S`, `보다 크면`→`이상이면` 변경 후 `python3 scripts/transcribe_check.py p2` 실행 → `옮겨 적기 확인: 같다`(종료 코드 0) 재현(**F6**).
4. `python3 scripts/usage_export.py --check` 및 `bash scripts/models.sh`, `logs/raw/claude/*.jsonl` 검사 → 원본 로그는 `claude-opus-5-5`인데 `AI_USAGE.md`·`GIT_LOG.txt`는 `Claude Fable 5.2`로 적힌 불일치 확인(**F9**).
5. `/tmp/qa_GEMINI/problems/p2/p2.cpp`의 `WindowQueue::pop_front()`에서 `head_ >= 75`일 때 창을 통째로 비우는 버그 주입 후 `verify.py` 실행 → 60줄 이하 퍼징과 기존 사례를 모두 통과해 `PASS` 판정 재현(**F3**).

## 7. 내가 틀릴 수 있는 곳
- 리허설 2의 모델 이름 불일치(**F9**)는 당시 대화창을 열었던 순서 때문일 수 있으나, 실전에서도 `models.sh`를 실행한 뒤 기존 창을 닫지 않거나 AI가 모델 이름을 짐작해 적으면 똑같이 재발한다.
- 평가기가 표준 오류(`stderr`)를 완전히 무시한다면 **F1**의 `stderr` 요약 자체는 감점되지 않을 수 있으나, 지어낸 거부 이유 글자를 표준 출력(`stdout`)에 찍는 규칙(**F1**)은 어떤 평가기에서도 오답이 된다.

### 부록: 지난 외부 검토(`qa/2026-11-12/`) 대비 미해결 항목 확인
보고서 작성 완료 후 `qa/2026-11-12/HARNESS_QA_REPORT.md`와 `HARNESS_QA_REVIEW_claude.md`를 열어 대조한 결과, 당시 지적된 항목 중 아래 4가지가 v6(`7861d1c`)에서도 완전히 해결되지 않고 남아 있다.
1. **`H8` (`log_step.sh`의 `git add -A`)**: 단계별 산출물만 스테이징하라는 지적이 있었으나 `scripts/log_step.sh:41`은 여전히 `git add -A`를 실행해 병렬 창 작업 시 다른 문제의 미완성 파일까지 함께 커밋한다(**F4**).
2. **`3.1`·`3.2` (미실행 줄과 변형 시험의 판정 반영)**: 검증 표에 행은 추가되었으나 `report.condition(...)`을 호출하지 않아, 미실행 줄이 남거나 변형 시험이 0곳(`0/0`)이어도 여전히 `판정: PASS`가 나온다(**F2, F5**).
3. **`9절 #5` (다른 작업 대화가 섞이지 않을 것)**: Claude Code 로그는 프로젝트 폴더별로 모으게 고쳐졌으나, `scripts/collect_logs.py:397`의 Codex 로그는 여전히 `~/.codex` 전체에서 시각만으로 긁어와 다른 폴더 작업이 섞인다(**F9**).
4. **`H4` (시작·대기·재개 시각 기록)**: `clock.sh`에 `wait`가 만들어졌으나 `.claude/skills/solve/SKILL.md` 절차에서 `wait`를 부르는 곳이 없어 현황판 대기 시간이 `0분`으로 남는다(**F12**).





