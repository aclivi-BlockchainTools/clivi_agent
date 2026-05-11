#!/bin/bash
# =============================================================================
# stress_test.sh — Bateria d'estrès amb repos complexos
#
# Prova la detecció de stacks en repos monorepo, multi-servei i exòtics.
# TOTS en mode `analyze` (dry-run, sense executar).
#
# Ús:
#   ./stress_test.sh           # bateria completa (7 repos)
#   ./stress_test.sh --keep    # no neteja el workspace després
# =============================================================================
set +e
KEEP="false"
for arg in "$@"; do
    [ "$arg" = "--keep" ] && KEEP="true"
done

AGENT="${AGENT:-$HOME/universal-agent/universal_repo_agent_v5.py}"
WORKSPACE="${WORKSPACE:-$HOME/universal-agent-workspace}"
REPORT="$HOME/agent_stress_report.md"
TMPLOG="/tmp/stress_$$.log"

REPOS=(
    "turborepo|monorepo|https://github.com/vercel/turborepo|180"
    "nx-examples|monorepo-nx|https://github.com/nrwl/nx-examples|180"
    "phoenix|elixir|https://github.com/phoenixframework/phoenix|180"
    "deno|deno|https://github.com/denoland/deno|180"
    "dotnet-samples|dotnet|https://github.com/dotnet/samples|180"
    "microservices-demo|multi|https://github.com/GoogleCloudPlatform/microservices-demo|240"
    "lerna|monorepo-lerna|https://github.com/lerna/lerna|180"
)

OK=0; FAIL=0; TOTAL=${#REPOS[@]}
RESULTS=(); START=$(date +%s)
echo "================================================================================"
echo "🧪 BATERIA D'ESTRÈS — Universal Repo Agent — $TOTAL repos complexos"
echo "   Mode: analyze (detecció de stack, sense execució)"
echo "================================================================================"

for entry in "${REPOS[@]}"; do
    IFS='|' read -r name stack_kind url timeout <<< "$entry"
    printf "▶️  [%-22s] %-16s ... " "$name" "$stack_kind"
    REPO_START=$(date +%s)

    timeout "$timeout" python3 "$AGENT" \
        --input "$url" \
        --workspace "$WORKSPACE" \
        --approve-all --non-interactive --no-readme --no-model-refine \
        > "$TMPLOG" 2>&1
    RC=$?
    ELAPSED=$(($(date +%s) - REPO_START))

    # Extreu info de detecció del log
    DETECTED_STACK=$(grep -oP 'Serveis detectats \(\K[0-9]+' "$TMPLOG" || echo "?")
    STACK_TYPES=$(grep -oP '\- \S+ \(\K[^)]+' "$TMPLOG" | tr '\n' ' ' || echo "?")
    MONOREPO_WARN=$(grep -c "Monorepo detectat" "$TMPLOG" || echo "0")
    WARNINGS=$(grep -c "⚠️" "$TMPLOG" || echo "0")
    BD_HINT=$(grep "Cal BD:" "$TMPLOG" | head -1 | sed 's/.*Cal BD: //' || echo "-")

    if [ "$RC" -eq 0 ]; then
        printf "${GREEN}✅ OK${NC}  (%ss)\n" "$ELAPSED"
        OK=$((OK+1))
        RESULTS+=("|✅|$name|$stack_kind|${DETECTED_STACK} serveis|$STACK_TYPES|${ELAPSED}s||")
    elif [ "$RC" -eq 124 ]; then
        printf "${YELLOW}⏱️  TIMEOUT${NC}  (%ss)\n" "$ELAPSED"
        FAIL=$((FAIL+1))
        RESULTS+=("|⏱️|$name|$stack_kind|timeout|$STACK_TYPES|${ELAPSED}s|timeout|")
    else
        printf "${RED}❌ FAIL${NC}  (rc=%s, %ss)\n" "$RC" "$ELAPSED"
        FAIL=$((FAIL+1))
        ERR=$(grep -E "ERROR|Errno|Failed|Exception" "$TMPLOG" | tail -1 | head -c 100)
        RESULTS+=("|❌|$name|$stack_kind|${DETECTED_STACK} serveis|$STACK_TYPES|${ELAPSED}s|rc=$RC: $ERR|")
    fi

    # Info addicional de diagnòstic
    if [ "$RC" -ne 0 ] || [ "${DETECTED_STACK}" = "0" ] || [ "${DETECTED_STACK}" = "?" ]; then
        echo "       Stack: ${STACK_TYPES:-cap} | BD: ${BD_HINT} | Warnings: ${WARNINGS} | Monorepo: ${MONOREPO_WARN}"
    fi

    [ "$KEEP" = "false" ] && python3 "$AGENT" --workspace "$WORKSPACE" --stop "$name" > /dev/null 2>&1
done

TOTAL_TIME=$(($(date +%s)-START))
PCT=$((OK*100/TOTAL))
echo "================================================================================"
echo "📊 $OK/$TOTAL passats ($PCT%) · Temps total: ${TOTAL_TIME}s"
echo "================================================================================"

{
echo "# Informe Estrès — $(date '+%Y-%m-%d %H:%M')"
echo ""
echo "**$OK/$TOTAL ($PCT%)** · Temps: ${TOTAL_TIME}s · Mode: analyze (detecció)"
echo ""
echo "| Estat | Repo | Stack esperat | # Serveis | Tipus detectats | Temps | Detall |"
echo "|-------|------|--------------|-----------|-----------------|-------|--------|"
for r in "${RESULTS[@]}"; do echo "$r"; done
echo ""
echo "## Llegenda"
echo "- **Monorepo**: turborepo, nx, lerna — esperem warning \"Monorepo detectat\""
echo "- **Elixir**: phoenix — esperem detecció \`elixir/phoenix\`"
echo "- **Deno**: deno — esperem detecció \`deno/deno\`"
echo "- **.NET**: dotnet/samples — esperem detecció \`dotnet/aspnet\` o \`dotnet/dotnet\`"
echo "- **Multi**: microservices-demo — esperem múltiples serveis"
echo ""
echo "## Millores pendents"
echo "- Monorepos: el warning informa però no s'executen workspace-level installs"
echo "- Stacks nous (Deno, Elixir, .NET): detecció bàsica, sense execució real"
} > "$REPORT"
echo "📄 Informe: $REPORT"
rm -f "$TMPLOG"
