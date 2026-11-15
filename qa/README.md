# 하네스 점검 기록

하네스 자체를 외부 모델에게 리뷰받은 기록이다. 반영 여부는 `../docs/04_external_review.md` 에 정리했다.

| 경로 | 내용 |
|---|---|
| `../HARNESS_QA_BRIEF.md` | 외부 검토자에게 준 점검 지침 (2026-11-14, v6 기준) |
| `HARNESS_QA_REPORT_GPT.md` | OpenAI GPT (Codex) 의 보고서 |
| `HARNESS_QA_REPORT_GEMINI.md` | Google Gemini 4 Argon (Antigravity) 의 보고서 |
| `2026-11-12/` | 연습 1 뒤의 점검 기록: 의뢰서, Codex 보고서, Claude 교차 검토 |

보고서는 원문을 그대로 두었다. 맨 위의 "공개본 주"에 공개하면서 바꾼 것을 적었다.
두 검토자는 서로의 보고서를 보지 않고 썼다. 풀이 중의 Claude Code 는 이 폴더와 의뢰서를 읽지 못하게 막아 두었다(`.claude/settings.json`).
`scripts/qa_bundle.sh` 는 검토자에게 넘길 묶음을 `qa/_bundle/` 에 만든다(저장소에는 넣지 않는다).
