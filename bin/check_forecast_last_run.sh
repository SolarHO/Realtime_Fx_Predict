#!/usr/bin/env bash
set -euo pipefail

# 사용법: check_forecast_last_run.sh [PAIR]
PAIR="${1:-USDKRW}"

docker exec -i postgres bash -lc "
psql -U \$POSTGRES_USER -d \$POSTGRES_DB -F $'\t' -A -c \"
SELECT
  model,
  MAX(run_ts) AS last_run_ts,
  MAX(kst_date) AS last_kst_date,
  COUNT(*) FILTER (WHERE kst_date >= CURRENT_DATE - INTERVAL '14 days') AS rows_14d
FROM fx_forecast_daily
WHERE pair='${PAIR}'
GROUP BY model
ORDER BY last_run_ts DESC NULLS LAST;
\""
