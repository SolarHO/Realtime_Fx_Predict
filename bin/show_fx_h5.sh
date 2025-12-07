#!/usr/bin/env bash
set -euo pipefail
PAIR="${1:-USDKRW}"
LIM="${2:-50}"
PG="psql -U $POSTGRES_USER -d $POSTGRES_DB -F $'\t' -A -q -X -P pager=off"
docker exec -i postgres bash -lc \
"$PG -c \"SELECT kst_date, pair, model, y_pred, run_ts
           FROM fx_forecast_h5
           WHERE pair='${PAIR}'
           ORDER BY kst_date DESC, model
           LIMIT ${LIM};\""
