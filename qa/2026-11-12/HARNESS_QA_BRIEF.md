> 공개본 주: 날짜와 일부 출처 표현, 사용자 경로와 세션 번호를 가렸다. 상황을 드러내는 낱말은 과제, 평가, 실전 같은 말로 바꿨다. 그 밖의 내용은 그대로다.

# 하네스 품질 검사 의뢰서 (연습 1 실행 기준)

이 문서는 하네스 품질 검사를 맡은 세션에 넘기는 자료 묶음이다. 작업 폴더는 `~/cotest`(이하 루트)다. 아래 경로는 모두 루트 기준이다.

## 1. 무엇을 검사하나

**하네스**는 2026-11-11에 사전 준비로 만든 것이다(커밋 `[Claude Code (Fable 5.2, 데스크톱 앱)] 사전 준비`). 들어 있는 것:
- 규칙: `AGENTS.md`, `CLAUDE.md`
- 절차(스킬) 4개
- 검증 스크립트와 Codex 호출 스크립트
- 코드·문서 뼈대, 예외 점검표

**이번 실행**은 2026-11-12에 연습 문제 하나(`practice/pr1.md`, 주문 관리 체결·잔고)를 이 하네스로 처음부터 끝까지 푼 것이다.
- 단계: `/intake` → `/solve p1` → `/finish` → `/explain p1`
- 모델: Claude Code (Opus 5.5)가 주 작업자였다. Codex (gpt-6.1-sol)가 애매한 점 찾기, 독립 구현, 리뷰를 맡았다. 사람은 결정 카드에 답했다.

**검사의 목적**: 이 하네스가 실전에서 다음 세 가지를 해 주는지 판단하고, 고칠 점을 우선순위로 뽑는다.
- 정확한 답을
- 시간 안에
- 사람이 믿을 수 있는 근거와 함께

검사 대상은 **하네스**다. p1 답안의 품질은 하네스가 제대로 작동했는지 보여 주는 증거로만 본다.

## 2. 넘기는 자료 (읽는 순서)

### A. 하네스 정의 (먼저 읽기)
| 경로 | 내용 |
|---|---|
| `README.md` | 사용자용 안내, 전체 흐름 |
| `AGENTS.md`, `CLAUDE.md` | 모든 에이전트 공통 규칙, Claude Code 보충 규칙 |
| `.claude/skills/{intake,solve,finish,explain}/SKILL.md` | 절차 4개 |
| `templates/FORMATS.md` | 문서 형식(SPEC, EDGE, DECISIONS, 결정 카드, REPORT, EXPLAIN) |
| `templates/main.cpp`, `templates/gen.py`, `templates/check.py` | 코드, 생성기, 검사기 뼈대 |
| `CHECKLIST.md` | 예외 점검표 |
| `prompts/{ambig,alt,review}.md` | Codex에게 주는 지시문 |
| `scripts/verify.sh`, `scripts/verify.py` | 3층 검증(정답 사례, 불변식, 독립 구현 무작위 비교) + 경고·sanitizer·큰 입력 시간 |
| `scripts/final_gate.sh` | 제출 직전 재검증, 통과 시 `submit/` 으로 복사 |
| `scripts/codex_ask.sh` | Codex를 빈 폴더에서 호출(독립성 보장) |
| `scripts/log_step.sh` | `AI_USAGE.md` 에 한 줄 추가 + `git add -A` + 커밋 |
| `scripts/new_problem.sh`, `collect_logs.sh`, `archive_run.sh` | 보조 |
| `selftest/`, `scripts/selftest.py`, `selftest/mutate.py` | 하네스 자체 시험(예제 문제 s1, 돌연변이 시험) |
| `.claude/settings.json` | 권한 설정 |

### B. 이번 실행의 산출물 (`problems/p1/`)
| 경로 | 내용 |
|---|---|
| `PROBLEM.md` | 원문(수정 금지 대상) |
| `AMBIG_claude.md`, `AMBIG_codex.md` | 두 모델이 따로 찾은 애매한 점 |
| `SPEC.md`, `EDGE.md` | 요구사항, 예외 표(E1\~E43) |
| `DECISIONS.md` | AI 결정 표 + 사람 결정 카드 7개(D1, D3, D14, D8, D17, D18, D20) |
| `tests/` | 정답 사례 31개(01\~31) |
| `gen.py`, `check.py` | 무작위 생성기, 불변식 검사기 |
| `p1.cpp` (= `submit/p1.cpp`) | 제출 답안 |
| `alt.cpp`, `ALT_NOTES.md` | Codex 2차 독립 구현 |
| `REVIEW_codex.md` | Codex 2차 리뷰 |
| `known_fail/` | 받아들인 한계의 반례(77줄)와 설명 |
| `VERIFY.txt`, `VERIFY.json` | 마지막 검증 결과 |
| `REPORT.md` | 문제 보고서 |
| `EXPLAIN.md` | 제출 뒤 코드 설명서 |
| `build/` (**git에 없음**, `.gitignore`) | 1차 리뷰 `REVIEW_codex_round1.md`, 1차 독립 구현 `alt_old_longdouble.cpp`, `ALT_NOTES_old.md`, 빌드 결과물 |

### C. 기록
| 경로 | 내용 |
|---|---|
| `AI_USAGE.md` | 단계별 시간순 기록, 도구·모델, 문제별 AI/사람 역할 |
| `git log` | 단계마다 커밋 1개(총 18개 이상) |
| `logs/codex_*_p1_*.log` | p1 의 Codex 호출 5회(ambig 1, alt 2, review 2)의 지시문과 출력. `*_s1_*` 2개는 사전 준비 단계의 자체 시험 |
| `logs/raw/claude/<세션>.jsonl` (2.4MB) | Claude Code 원본 대화 **전체**(문맥 요약 이전 부분 포함) |
| `logs/raw/codex/rollout-*.jsonl` | Codex 원본 기록 5개 |
| `claude_session.txt` (루트, 440줄) | `/export` 결과. **문맥 요약 이후 부분만** 들어 있다. 전체는 위 jsonl |

## 3. 실행 요약 (기계 기록 기준)

### 시간순 진행 (`AI_USAGE.md`, `logs/` 파일명 기준)

| 시각 (11-12) | 일 | 걸린 시간 |
|---|---|---|
| 17:20 | `/intake` 시작. Codex ambig 호출 | |
| 17:26 | SPEC, EDGE, DECISIONS 완료. 사람에게 카드 4개 | intake 6분 |
| 17:38 | 사람 답(D1은 추천 A 대신 C) | 사람 12분 |
| 17:56 | Codex 1차 독립 구현 호출 | |
| 18:00 | 테스트 28개, 구현, gen/check 작성 | |
| 18:02 | verify FAIL(64비트 넘는 번호) → D17 카드, PASS. Codex 1차 리뷰 호출 | |
| 18:07 | 1차 리뷰: 지적 3건. long double 정밀도 버그를 재현하고 테스트 29\~31 추가 | |
| 18:08 | **25분 제한 초과** 중간 보고(FAIL), D18 카드 | solve 시작 뒤 약 30분 |
| 18:17 | 사람 답 D18 A, D17 A | |
| 18:22 | 큰 정수 분수로 다시 구현. 108초 → D19(분모 상한)로 0.24초 | |
| 18:27 | Codex 2차 독립 구현과 비교 PASS. 2차 리뷰 호출 | |
| 18:35 | 2차 리뷰: D19 때문에 경계 근처 값이 틀림 → D20 카드 | |
| 18:36 | solve 완료(PASS, known_fail 1건) | solve 약 58분 |
| 19:39 | 사람 답 D20 A, 재검증 PASS | 사람 대기 약 63분 |
| 20:01 | `/finish`: final_gate 통과, 기록 수집 | |
| 20:20 | `/explain p1` | |

### 결과 지표

**최종 판정**: PASS. `VERIFY.txt` 기준으로 아래가 모두 통과했다.
- 정답 사례 31개
- 경고 없음
- ASan/UBSan
- 불변식 검사
- 독립 구현과의 무작위 비교 1000회(차이 0)
- 20만 줄 입력 0.28초

**남은 한계**: `known_fail/` 반례 1개(사람이 D20-A로 받아들임).

**결정 수**: 사람 7개(처음 4개, solve 중 3개), AI 10여 개. D16은 D18로 대체되었다.

**리뷰가 찾은 결함**: 4건. 3건은 고쳤고, 1건은 사람에게 올려 받아들였다. 이 4건은 **3층 무작위 비교로는 잡히지 않았다**.

**검증 실행 중의 일**: verify FAIL 원인 3종이 나왔다(번호 범위, check.py 오탐, alt의 `+3` 해석). 같은 실패가 세 번 이어지는 상황(중단 기준)은 없었다.

## 4. 실행 중 Claude가 본 하네스 문제 후보 (검증 필요)

아래는 작업자(Claude Code)의 자기 관찰이다. 작업자 자신의 하네스를 평가한 것이므로 편향이 있을 수 있다. 각 항목을 근거 파일로 직접 확인해 주길 바란다.

| # | 관찰 | 근거 |
|---|---|---|
| H1 | **독립 구현 비교가 같은 원인의 오류를 놓쳤다.** 1차 alt도 `long double` 이라 두 구현이 같은 정밀도 오류를 내고 1000회 모두 일치했다. 결함은 리뷰에서만 잡혔다. `prompts/alt.md` 가 "다른 수치 표현을 써라"를 요구하지 않는다 | `build/alt_old_longdouble.cpp`, `build/REVIEW_codex_round1.md`, 커밋 18:07 |
| H2 | **AI가 정한 D19가 출력에 영향을 주었다.** "6자리 출력에는 영향 없다"는 근거가 틀렸다. AGENTS.md 기준("확신도가 낮고 출력이 달라진다"면 사람에게)으로 보면 처음부터 올렸어야 했을 수 있다. 확신도 "중간"이면 올리지 않아도 되는 빈틈이 있다 | `DECISIONS.md` D19, `REVIEW_codex.md` |
| H3 | **"받아들인 한계(known_fail)"를 담을 자리가 하네스에 없다.** 작업 중에 임시로 만들었다. `verify.sh`, `final_gate.sh`, `FORMATS.md`, solve 스킬 모두 이것을 모른다. 규칙 2(테스트를 구현에 맞추지 않는다)와 PASS 판정 사이의 공백이다 | `known_fail/README.md`, `scripts/verify.py` |
| H4 | **25분 제한이 맞지 않았다.** 25분에 멈추고 보고했지만 사람의 결정이 필요한 상태였다. 실제 solve는 약 58분 걸렸다. 문제가 여러 개인 실전에서 시간 배분 규칙이 충분한가 | `AI_USAGE.md` 18:08 |
| H5 | **결정 카드가 비용을 낮게 적었다.** D1 카드의 C 선택지 위험이 "계산이 복잡해진다" 한 줄이었다. 실제로는 큰 정수 구현, 성능 문제(108초), 추가 결정 3개(D18\~D20)로 이어졌다. 카드 형식이 "나중에 바꾸는 비용"을 과소평가하게 만드는가 | `DECISIONS.md` D1 |
| H6 | **무작위 시험의 seed가 고정이다**(`--seed` 기본값 20261115). `verify.sh` 와 `final_gate.sh` 가 매번 같은 1000개 입력만 시험한다 | `scripts/verify.py:141` |
| H7 | **보관한 증거 일부가 git 밖에 있다.** `build/` 는 `.gitignore` 대상이라 1차 리뷰 원문과 1차 alt가 커밋되지 않았다 | `.gitignore`, `git check-ignore` |
| H8 | **`log_step.sh` 가 `git add -A` 로 모든 파일을 커밋한다.** 사용자가 루트에 만든 `claude_session.txt` 도 그대로 커밋되었다. 원본 대화 jsonl(개인 정보가 있을 수 있음)도 git에 들어 있다 | `scripts/log_step.sh` |
| H9 | **`/export` 경로 안내가 지켜지지 않았다**(`logs/` 대신 루트에 저장). 문맥 요약 뒤에 export하면 앞부분이 빠진다. 제출 기록의 완전성을 하네스가 확인하지 않는다 | `claude_session.txt` 440줄, finish 스킬 2.5 |
| H10 | **보고서 숫자를 손으로 맞춘다.** REPORT의 실행 시간이 마지막 검증과 달라 손으로 고쳤다(0.25 → 0.28). REPORT와 AI_USAGE가 자동 생성이 아니다 | 커밋 19:39:58 |
| H11 | **Codex 실패 시 대비책(Agent 도구)은 이번에 한 번도 쓰이지 않았다.** 그 경로는 미검증이다 | `AI_USAGE.md` |
| H12 | **check.py가 종목 `005930` 을 "앞에 0이 붙은 숫자"로 오탐했다.** `templates/check.py` 의 안내가 이런 실수를 막는가 | AI_USAGE 18:02 |
| H13 | **작업자 Claude가 alt.cpp를 직접 고쳤다**(`+3` 해석, solve 스킬이 허용함). 고친 뒤의 비교 결과가 여전히 독립적인 근거인가 | `alt.cpp` 주석, 커밋 18:27 |
| H14 | **자동 모드에서 Bash 호출 한 번이 막혔다**가 같은 명령으로 다시 성공했다. 사소함 | 원본 jsonl |

## 5. 검사해 주길 바라는 질문

1. 규칙 준수: 각 스킬의 단계가 실제로 지켜졌나? 기록(커밋, AI_USAGE)과 원본 대화로 대조해 주길 바란다. 예를 들어 solve 1단계는 "독립 구현을 먼저 백그라운드로"인데, alt 호출은 17:56이었다.
2. 근거의 질: REPORT/VERIFY의 주장 가운데 기계 출력 없이 말로만 한 것이 있나?
3. 결정 흐름: 사람에게 올린 것과 AI가 정한 것의 경계가 적절했나? 카드 7개는 너무 많았나, 적었나?
4. 검증 설계: 3층 검증의 빈틈(H1, H3, H6)이 실전에서 얼마나 위험한가? 어떻게 고치나?
5. 시간: 실전(여러 문제, 정해진 시간)에서 이 흐름이 시간 안에 끝나는가? 어디를 줄일 수 있나?
6. 사용자 관점: 사람이 받은 메시지와 카드가 사람에게 이해 가능하고 답하기 쉬웠나? 근거는 `claude_session.txt` 와 jsonl 안의 사용자 메시지다.
7. 제출 패키지: AI 사용 내역 제출 요건(전체 대화, 사용 모델)을 하네스가 빠짐없이 채우나?
8. 위 H1\~H14 각각에 대해: 맞는가, 심각도는 어느 정도인가, 고친다면 어느 파일을 고치나?

## 6. 검사 세션이 지킬 것

- **기존 파일을 고치지 않는다.** 결과는 `qa/` 아래 새 파일(예: `qa/HARNESS_QA_REPORT.md`)로 쓴다.
- `git push`, 외부 업로드, 패키지 설치를 하지 않는다. `logs/raw/` 에는 개인 정보가 있을 수 있으니 외부 서비스로 보내지 않는다.
- 주장에는 근거 파일과 행, 또는 직접 돌린 명령의 출력을 붙인다. 직접 돌릴 수 있는 것들:
  - `scripts/verify.sh p1`: `VERIFY.txt` 를 덮어쓴다. 돌린 뒤 결과가 PASS인지만 확인한다.
  - `python3 scripts/selftest.py`
  - 반례 재현: `g++ -std=c++20 -O2 -o /tmp/p1 problems/p1/p1.cpp && /tmp/p1 < problems/p1/known_fail/review2_near_boundary.in | tail -1`
- 하네스를 만든 쪽도 실행한 쪽도 Claude다. 가능하면 **다른 모델(예: Codex)이 검사하거나 교차 검사하는 것**을 권한다.
