#!/bin/bash
set +e
KEEP="false"; MODE="full"
for arg in "$@"; do
    [ "$arg" = "quick" ] && MODE="quick"
    [ "$arg" = "--keep" ] && KEEP="true"
done

AGENT="${AGENT:-$HOME/universal-agent/universal_repo_agent_v5.py}"
WORKSPACE="${WORKSPACE:-$HOME/universal-agent-workspace}"
REPORT="$HOME/agent_bench_report.md"
TMPLOG="/tmp/bench_$$.log"

REPOS_FULL=(
    "flask|analyze|https://github.com/pallets/flask|120"
    "fastapi|analyze|https://github.com/tiangolo/fastapi|180"
    "streamlit-example|run|https://github.com/streamlit/streamlit-example|600"
    "express|analyze|https://github.com/expressjs/express|180"
    "vite|analyze|https://github.com/vitejs/vite|240"
    "django|analyze|https://github.com/django/django|240"
    "nextjs|analyze|https://github.com/vercel/next.js|240"
    "gradio|analyze|https://github.com/gradio-app/gradio|240"
    "fastapi-mongo|run|https://github.com/mongodb-developer/mongodb-with-fastapi|600"
    "go-example|analyze|https://github.com/golang/example|180"
)
REPOS_QUICK=(
    "flask|analyze|https://github.com/pallets/flask|120"
    "express|analyze|https://github.com/expressjs/express|120"
    "fastapi|analyze|https://github.com/tiangolo/fastapi|180"
    "streamlit-example|run|https://github.com/streamlit/streamlit-example|600"
    "django|analyze|https://github.com/django/django|180"
)
[ "$MODE" = "quick" ] && REPOS=("${REPOS_QUICK[@]}") || REPOS=("${REPOS_FULL[@]}")

OK=0; FAIL=0; TOTAL=${#REPOS[@]}
RESULTS=(); START=$(date +%s)
echo "================================================================"
echo "🧪 BATERIA DE TEST — Universal Repo Agent ($MODE) — $TOTAL repos"
echo "================================================================"

for entry in "${REPOS[@]}"; do
    IFS='|' read -r name kind url timeout <<< "$entry"
    printf "▶️  [%-20s] %-9s ... " "$name" "$kind"
    REPO_START=$(date +%s)
    if [ "$kind" = "analyze" ]; then
        timeout "$timeout" python3 "$AGENT" --input "$url" --workspace "$WORKSPACE" --no-readme --no-model-refine > "$TMPLOG" 2>&1
    else
        timeout "$timeout" python3 "$AGENT" --input "$url" --workspace "$WORKSPACE" --execute --approve-all --non-interactive --no-readme --no-model-refine > "$TMPLOG" 2>&1
    fi
    RC=$?; ELAPSED=$(($(date +%s) - REPO_START))
    if [ "$kind" = "run" ] && [ "$RC" -eq 0 ]; then
        SO=$(grep -c "✅" "$TMPLOG"); SF=$(grep -c "❌" "$TMPLOG"); TS=$((SO+SF))
        [ "$TS" -gt 0 ] && [ "$SO" -lt $((TS/2)) ] && RC=2
    fi
    if [ "$RC" -eq 0 ]; then
        printf "33[32m✅ OK33[0m  (%ss)\n" "$ELAPSED"; OK=$((OK+1))
        RESULTS+=("|✅|$name|$kind|${ELAPSED}s||")
    elif [ "$RC" -eq 124 ]; then
        printf "33[33m⏱️  TIMEOUT33[0m  (%ss)\n" "$ELAPSED"; FAIL=$((FAIL+1))
        RESULTS+=("|⏱️|$name|$kind|${ELAPSED}s|timeout|")
    else
        printf "33[31m❌ FAIL33[0m  (rc=%s, %ss)\n" "$RC" "$ELAPSED"; FAIL=$((FAIL+1))
        ERR=$(grep -E "ERROR|Errno|Failed" "$TMPLOG" | tail -1 | head -c 80)
        RESULTS+=("|❌|$name|$kind|${ELAPSED}s|rc=$RC: $ERR|")
    fi
    [ "$KEEP" = "false" ] && python3 "$AGENT" --workspace "$WORKSPACE" --stop "$name" > /dev/null 2>&1
done

TOTAL_TIME=$(($(date +%s)-START)); PCT=$((OK*100/TOTAL))
echo "================================================================"
echo "📊 $OK/$TOTAL passats ($PCT%) · Temps total: ${TOTAL_TIME}s"
echo "================================================================"
{
echo "# Informe Bateria — $(date '+%Y-%m-%d %H:%M')"
echo ""
echo "**$OK/$TOTAL ($PCT%)** · Temps: ${TOTAL_TIME}s · Mode: $MODE"
echo ""
echo "| Estat | Repo | Tipus | Temps | Detall |"
echo "|-------|------|-------|-------|--------|"
for r in "${RESULTS[@]}"; do echo "$r"; done
} > "$REPORT"
echo "📄 Informe: $REPORT"
rm -f "$TMPLOG"
