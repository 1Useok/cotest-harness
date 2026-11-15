@AGENTS.md

## Claude Code 전용 보충

- 절차는 스킬로 부른다: `/intake`(문제 접수와 결정), `/solve p1`(문제 하나 풀고 검증), `/probe p1 <상황>`(사람의 "이러면?"을 실행해 보기), `/finish`(제출 준비), `/explain p1`(제출 뒤 설명서), `/ask <질문>`(사람의 질문에 답하는 창. 파일을 고치지 않는다).
- 독립된 일(애매한 점 찾기, 독립 구현, 정답 사례 교차 확인, 리뷰)은 `scripts/codex_ask.sh`로 Codex에게 맡긴다.
  - 출력이 `OK:` 로 시작할 때만 성공이다. `CODEX_NOT_FOUND`나 `CODEX_FAILED`가 나오면 대비책을 쓴다: Agent 도구로 새 에이전트를 띄우고, `prompts/` 의 같은 프롬프트와 **같은 파일만** 준다(alt 에는 `DECISIONS.md` 의 `## 구현 메모` 절을 빼고 주고, `alt.cpp` 와 `gen2.py` 를 받는다). 대비책을 썼다는 사실을 `log_step.sh`에 적는다. 같은 회사 모델이라 독립성이 약하다는 점을 보고서에 적는다.
  - 교차 확인(cases)의 대비책: `mkdir -p /tmp/xc_pN && scripts/xcheck.sh prepare pN /tmp/xc_pN` 으로 입력만 꺼내고, `PROBLEM.md` 와 `DECISIONS.md`(구현 메모 절은 빼고)를 그 폴더에 복사한다. 새 에이전트에게 `prompts/cases.md` 를 주고 **그 폴더만** 읽고 쓰게 한다. 끝나면 `scripts/xcheck.sh ingest pN /tmp/xc_pN "Claude 하위 에이전트"`.
- 기대 출력이나 옮겨 적은 문제를 사람에게 확인해 달라고 하지 않는다. 사람은 결정 카드에만 답한다.
- 오래 걸리는 명령(Codex 호출, 검증, 변형 시험)은 백그라운드로 돌리고 그동안 다음 일을 한다.
- `log_step.sh`의 "누가"에는 **지금 실제로 쓰는** 모델 이름을 적는다. 예: `"Claude Code (Fable 5.2)"`, `"Claude Code (Opus 5.5)"`. Codex 는 `codex_ask.sh` 가 출력한 모델 이름을 그대로 쓴다.
- `runs/`(지난 연습의 보관), `qa/`, `HARNESS_QA_BRIEF.md`(하네스 점검 자료)는 읽지 않는다. 지난 답안과 정답 방향을 보고 풀면 안 된다.
- **사용자에게 보이는 글은 처음부터 끝까지 한국어다.** 생각을 정리하는 중간 설명도 한국어로 쓴다.
- 사용자에게 결정을 보여 줄 때는 `DECISIONS.md` 의 카드를 그대로 보여 주고, 답을 한 줄로 받을 수 있게 한다. 예: `D1: A, D3: B`. 답을 기다리며 멈추지 않는다.
- PDF 와 그림으로 온 문제는 Read 도구로 직접 읽는다. 읽지 못하는 형식(옛 한글 `.hwp` 등)은 바로 사용자에게 알린다.
- 사용자에게 보여 줄 입력과 출력은 파일 경로로 가리키지 말고 메시지에 그대로 싣는다.
- 대화가 길어지면 앞 내용이 요약되며 사라질 수 있다. 중요한 것은 대화가 아니라 파일(SPEC, EDGE, DECISIONS, REPORT)에 둔다. 지금 상태가 헷갈리면 `scripts/board.sh` 를 돌린다.
- 문제가 여럿이면 대화창 하나가 문제 하나를 맡는다. 다른 문제의 폴더를 고치지 않는다.
