#!/usr/bin/env bash
# 어떤 모델로 풀지 한 곳에서 정하고, 실제로 그 모델이 쓰였는지 확인한다.
# 사용:
#   scripts/models.sh          # 지금 설정 + 최근 창들이 실제로 쓴 모델과 강도
#   scripts/models.sh fable    # Claude Fable 5.2 (high) + Codex gpt-6-astra (high). 하위 에이전트는 Opus 5.5
#   scripts/models.sh opus     # Claude Opus 5.5 (high) + Codex gpt-6.1-sol (high). 리허설 2에서 끝까지 돌려 본 조합
#   scripts/models.sh fable high max   # 둘째 인자는 Claude 의 강도, 셋째는 Codex 의 강도(생략하면 high)
#       Claude 강도: low medium high xhigh / Codex 강도: low medium high xhigh max
#       Codex 강도가 xhigh 나 max 면 호출 하나의 제한 시간을 900초에서 1500초로 늘린다(models.conf 의 CODEX_TIMEOUT).
#       Codex 강도와 제한 시간은 다음 호출부터 바로 적용된다(창을 다시 열 필요가 없다).
#
# 바꾸는 것은 두 파일이다.
#   .claude/settings.json 의 model, effortLevel, env.CLAUDE_CODE_SUBAGENT_MODEL  (Claude Code)
#   models.conf 의 CODEX_MODEL, CODEX_EFFORT, CODEX_TIMEOUT                      (scripts/codex_ask.sh 가 읽는다)
# **바꾼 뒤에 새로 연 대화창부터 적용된다.** 이미 열려 있는 창은 닫고 새로 연다.
# 대화창에서 /model 로 직접 고르면 그 창은 그쪽이 우선이다. 진행 중에는 /model 을 건드리지 않는다.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile="${1:-show}"

case "$profile" in
  fable) c_model=fable; c_effort=high; sub_model=opus; x_model=gpt-6-astra; x_effort=high ;;
  opus)  c_model=opus;  c_effort=high; sub_model="";   x_model=gpt-6.1-sol; x_effort=high ;;
  show)  ;;
  *) echo "사용: scripts/models.sh [fable|opus] [Claude 강도] [Codex 강도]   (인자 없이 치면 지금 설정을 보여 준다)"; exit 2 ;;
esac
if [ "$profile" != show ]; then
  c_effort="${2:-$c_effort}"; x_effort="${3:-$x_effort}"
  case "$c_effort" in low|medium|high|xhigh) ;; *) echo "Claude 강도는 low, medium, high, xhigh 가운데 하나입니다: $c_effort"; exit 2 ;; esac
  case "$x_effort" in low|medium|high|xhigh|max) ;; *) echo "Codex 강도는 low, medium, high, xhigh, max 가운데 하나입니다: $x_effort"; exit 2 ;; esac
  case "$x_effort" in xhigh|max) x_timeout=1500 ;; *) x_timeout=900 ;; esac
fi

if [ "$profile" != show ]; then
  python3 - "$ROOT/.claude/settings.json" "$c_model" "$c_effort" "$sub_model" <<'EOF' || { echo "settings.json 을 고치지 못했습니다"; exit 1; }
import json, sys
path, model, effort, sub = sys.argv[1:5]
d = json.load(open(path, encoding="utf-8"))
d["model"] = model
d["effortLevel"] = effort
env = d.get("env", {})
if sub:
    env["CLAUDE_CODE_SUBAGENT_MODEL"] = sub
else:
    env.pop("CLAUDE_CODE_SUBAGENT_MODEL", None)
if env:
    d["env"] = env
else:
    d.pop("env", None)
# 읽기 쉬운 순서: 모델 설정을 맨 위에
out = {k: d[k] for k in ("model", "effortLevel", "env") if k in d}
out.update({k: v for k, v in d.items() if k not in out})
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
    f.write("\n")
EOF
  {
    echo "# scripts/models.sh 가 쓴다. scripts/codex_ask.sh 가 읽는다."
    echo "# 환경 변수 CODEX_MODEL, CODEX_EFFORT 가 있으면 그쪽이 우선이다."
    echo "CODEX_MODEL=$x_model"
    echo "CODEX_EFFORT=$x_effort"
    echo "CODEX_TIMEOUT=$x_timeout"
  } > "$ROOT/models.conf"
  echo "바꿨습니다. 열려 있는 Claude Code 대화창은 닫고 새로 여세요."
  echo
fi

python3 - "$ROOT" <<'EOF'
import json, os, sys, time, glob, collections
root = sys.argv[1]
d = json.load(open(os.path.join(root, ".claude", "settings.json"), encoding="utf-8"))
names = {"fable": "Claude Fable 5.2", "opus": "Claude Opus 5.5", "sonnet": "Claude Sonnet", "haiku": "Claude Haiku"}
m = d.get("model")
print("== 지금 설정")
print(f"  Claude Code   : {names.get(m, m) if m else '(정하지 않음: 사용자 설정이나 기본값을 따른다)'}, 강도 {d.get('effortLevel', '(정하지 않음)')}")
sub = (d.get("env") or {}).get("CLAUDE_CODE_SUBAGENT_MODEL")
print(f"  하위 에이전트 : {names.get(sub, sub) if sub else '대화창과 같은 모델'}")
conf = {}
p = os.path.join(root, "models.conf")
if os.path.exists(p):
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip()
cm = os.environ.get("CODEX_MODEL") or conf.get("CODEX_MODEL") or "gpt-6.1-sol (기본값)"
ce = os.environ.get("CODEX_EFFORT") or conf.get("CODEX_EFFORT") or "high (기본값)"
ct = os.environ.get("CODEX_TIMEOUT") or conf.get("CODEX_TIMEOUT") or "900"
print(f"  Codex         : {cm}, 강도 {ce}, 호출 하나의 제한 {ct}초" + ("   <- 환경 변수가 models.conf 보다 우선하고 있다" if os.environ.get("CODEX_MODEL") else ""))

# 실제로 쓰인 것: 최근 12시간 안에 바뀐 대화 기록에서 읽는다
print("== 최근 12시간에 실제로 쓰인 모델 (대화 기록에서 읽음)")
proj = os.path.expanduser("~/.claude/projects/" + root.replace("/", "-"))
since = time.time() - 12 * 3600
files = [f for f in glob.glob(proj + "/*.jsonl") + glob.glob(proj + "/*/subagents/*.jsonl") if os.path.getmtime(f) >= since]
if not files:
    print("  Claude Code   : 기록 없음 (새 창에서 한 번 물어본 뒤 다시 본다)")
for f in sorted(files, key=os.path.getmtime):
    c = collections.Counter()
    first = ""
    for line in open(f, encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "user" and not first:
            msg = e.get("message") or {}
            cont = msg.get("content")
            text = cont if isinstance(cont, str) else " ".join(x.get("text", "") for x in cont if isinstance(x, dict)) if isinstance(cont, list) else ""
            if "<command-name>" in text:
                name = text.split("<command-name>", 1)[1].split("<", 1)[0]
                args = text.split("<command-args>", 1)[1].split("<", 1)[0] if "<command-args>" in text else ""
                text = name + " " + args
            first = " ".join(text.split())[:28]
        if e.get("type") == "assistant":
            mod = e.get("requestedModel") or (e.get("message") or {}).get("model")
            if mod:
                c[(mod, e.get("effort"))] += 1
    if c:
        kind = "하위" if "/subagents/" in f else "창  "
        used = ", ".join(f"{mod} 강도 {eff} ({n}회)" for (mod, eff), n in c.most_common())
        print(f"  {kind} {time.strftime('%H:%M', time.localtime(os.path.getmtime(f)))} {first or '-':<28} {used}")
logs = [f for f in glob.glob(os.path.join(root, "logs", "codex_*.log")) if os.path.getmtime(f) >= since]
c = collections.Counter()
for f in logs:
    for line in open(f, encoding="utf-8", errors="replace"):
        if line.startswith("# 모델:"):
            c[line[2:].split(", 실행 파일")[0].strip()] += 1
            break
print("  Codex         : " + (", ".join(f"{k} ({n}회)" for k, n in c.most_common()) if c else "기록 없음"))
EOF
