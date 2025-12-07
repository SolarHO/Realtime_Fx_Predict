#!/usr/bin/env bash
set -euo pipefail

NET=fx-stack_fxnet
IMG=fxstack/forecast:any
PAIR=${PAIR:-USDKRW}
CTX=${CTX:-96}
EPOCHS=${EPOCHS:-200}
LR=${LR:-1e-3}

PG_OPTS=(-e POSTGRES_DB=fxdb -e POSTGRES_USER=fxuser -e POSTGRES_PASSWORD=fxpass123 -e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432)
S3_OPTS=(-e SAVE_TO_MINIO=true -e MINIO_ENDPOINT=http://minio:9000 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin123 -e MINIO_BUCKET=fx-raw)

run_one () {
  local MODEL="$1" H="$2" TBL
  case "$H" in
    1) TBL=fx_forecast_daily ;;
    5) TBL=fx_forecast_h5 ;;
    7) TBL=fx_forecast_h7 ;;
    *) echo "unsupported H=$H"; exit 1 ;;
  esac
  echo "[run] MODEL=$MODEL H=$H -> $TBL"
  docker run --rm --network "$NET" \
    -e MODEL="$MODEL" -e PAIR="$PAIR" -e CTX="$CTX" -e H="$H" \
    -e EPOCHS="$EPOCHS" -e LR="$LR" \
    -e FORECAST_TABLE="$TBL" \
    "${PG_OPTS[@]}" "${S3_OPTS[@]}" \
    "$IMG"
}

# === 하루치(=기존) ===
run_one dlinear 1
run_one arima   1
run_one lstm    1
run_one gru     1   # 필요 없으면 주석

# === 5일치(오늘 최신 실행만 뷰로 노출) ===
run_one dlinearh5 5
run_one lstmh5    5
run_one gruh5     5
run_one arimah5   5

# === 7일치(오늘 최신 실행만 뷰로 노출) ===
run_one dlinearh7 7
run_one lstmh7    7
run_one gruh7     7
run_one arimah7   7
