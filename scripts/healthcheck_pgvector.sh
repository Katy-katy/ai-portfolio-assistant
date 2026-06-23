#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[FAIL] .env not found at ${ENV_FILE}"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [[ "${RAG_BACKEND:-}" != "pgvector" ]]; then
  echo "[FAIL] RAG_BACKEND is '${RAG_BACKEND:-}', expected 'pgvector'"
  exit 1
fi

if [[ -z "${PGVECTOR_DSN:-}" ]]; then
  echo "[FAIL] PGVECTOR_DSN is empty in .env"
  exit 1
fi

PSQL_BIN="/opt/homebrew/opt/postgresql@17/bin/psql"
if [[ ! -x "${PSQL_BIN}" ]]; then
  PSQL_BIN="$(command -v psql || true)"
fi

if [[ -z "${PSQL_BIN}" ]]; then
  echo "[FAIL] psql is not available"
  exit 1
fi

echo "[INFO] Using psql: ${PSQL_BIN}"

echo "[CHECK] Database connectivity"
"${PSQL_BIN}" "${PGVECTOR_DSN}" -v ON_ERROR_STOP=1 -c "SELECT 1;" >/dev/null
echo "[PASS] Connected to PostgreSQL"

echo "[CHECK] vector extension"
EXTENSION_COUNT="$(${PSQL_BIN} "${PGVECTOR_DSN}" -tAc "SELECT count(*) FROM pg_extension WHERE extname='vector';")"
if [[ "${EXTENSION_COUNT}" != "1" ]]; then
  echo "[FAIL] vector extension is not enabled"
  exit 1
fi
echo "[PASS] vector extension is enabled"

echo "[CHECK] Vector table exists"
TABLE_NAME="$(${PSQL_BIN} "${PGVECTOR_DSN}" -tAc "SELECT to_regclass('public.${PGVECTOR_TABLE:-knowledge_chunks}');" | xargs)"
if [[ -z "${TABLE_NAME}" || "${TABLE_NAME}" == "" ]]; then
  echo "[FAIL] Table '${PGVECTOR_TABLE:-knowledge_chunks}' does not exist"
  exit 1
fi
echo "[PASS] Table exists: ${TABLE_NAME}"

echo "[CHECK] Chunk counts"
TOTAL_ROWS="$(${PSQL_BIN} "${PGVECTOR_DSN}" -tAc "SELECT count(*) FROM ${PGVECTOR_TABLE:-knowledge_chunks};" | xargs)"
if [[ -z "${TOTAL_ROWS}" || "${TOTAL_ROWS}" == "0" ]]; then
  echo "[FAIL] Vector table is empty"
  exit 1
fi
echo "[PASS] Indexed chunks: ${TOTAL_ROWS}"

${PSQL_BIN} "${PGVECTOR_DSN}" -tAc "SELECT category || ':' || count(*) FROM ${PGVECTOR_TABLE:-knowledge_chunks} GROUP BY category ORDER BY category;" | sed 's/^/[INFO] /'

echo "[CHECK] API availability on http://localhost:8000"
API_RESPONSE="$(curl -s -X POST http://localhost:8000/run-multi-agent \
  -H "Content-Type: application/json" \
  -d '{"session_id":"pgvector_healthcheck","message":"Summarize Lamabot and related AI skills"}')"

if [[ -z "${API_RESPONSE}" ]]; then
  echo "[FAIL] Empty response from API"
  exit 1
fi

STATUS="$(printf '%s' "${API_RESPONSE}" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
if [[ "${STATUS}" != "success" ]]; then
  echo "[FAIL] API returned non-success status"
  echo "[INFO] Response: ${API_RESPONSE}"
  exit 1
fi

echo "[PASS] API returned success"

TOOL_TRACE_COUNT="$(printf '%s' "${API_RESPONSE}" | /usr/bin/python3 -c 'import json,sys; data=json.load(sys.stdin); runs=data.get("agent_runs",[]); count=0
for run in runs:
    tools=run.get("tools_called")
    if tools:
        count += len([t for t in str(tools).split(",") if t.strip()])
print(count)')"

if [[ "${TOOL_TRACE_COUNT}" == "0" ]]; then
  echo "[FAIL] No retrieval tool traces found in agent_runs"
  echo "[INFO] Response: ${API_RESPONSE}"
  exit 1
fi

echo "[PASS] Retrieval tool traces found in agent_runs: ${TOOL_TRACE_COUNT}"

echo "[OK] pgvector health check passed"
