# AI 사용 내역

## 사용한 도구와 모델

| 도구 | 모델 | 용도 |
|---|---|---|
| (제출 준비 때 실제로 쓴 것으로 채운다) | | |

## 미리 준비한 것

이 작업 공간(규칙 파일, 절차, 검증 스크립트, 코드 뼈대, 예외 점검표, 실무 함정 사전)은 사전 준비 단계에서 AI(Claude Code)의 도움으로 만들었다.
준비에 쓴 모델: Claude Fable 5.2(기획과 검수), Claude Opus 5.5 와 Claude Sonnet 하위 에이전트(구현과 조사). 실전 전에 이 작업 공간을 다른 회사 모델 둘(OpenAI Codex 의 GPT, Antigravity 의 Gemini 4 Argon)에게 점검받아 고쳤다(보고서는 `qa/`). 준비 단계의 기록은 `git log` 에 있다.
문제를 미리 알고 만든 것은 없다. 준비한 파일은 이 폴더에 그대로 있고, 작업 방식은 `HARNESS.md` 에 적었다.

## 문제별 요약

(제출 준비 때 문제마다 "AI가 한 일 / 사람이 한 일"을 적는다)

## 원본 기록

- `logs/claude_session*.txt` : Claude Code 대화 내보내기(대화창마다 하나)
- `logs/raw/` : Claude Code 와 Codex 의 원본 대화 기록. 목록은 `logs/MANIFEST.md`
- `logs/raw/side_questions.json` : 곁 질문(/btw, 옆 대화 패널)의 질문과 답. 대화 기록 파일에 남지 않아 따로 모은 것
- `logs/codex_*.log` : Codex 호출마다의 지시문과 출력
- `logs/GIT_LOG.txt` : 단계별 기록(누가, 언제, 무엇을)
- 문제별 `DECISIONS.md`, `REPORT.md`, `VERIFY.txt`

## 시간순 기록

| 시각 | 누가 | 무엇을 |
|---|---|---|
