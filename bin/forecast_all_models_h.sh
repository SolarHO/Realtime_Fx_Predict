#!/usr/bin/env bash
set -euo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

run_any() {
  local model="$1"; local h="$2"
  /usr/bin/docker run --rm --network fx-stack_fxnet \
    --entrypoint python \
    -v ~/fx-stack/forecast_multi/train_any.py:/app/train_any.py:ro \
    -e MODEL="$model" -e PAIR=USDKRW -e CTX=96 -e H="$h" \
    -e EPOCHS=200 -e LR=1e-3 \
    -e POSTGRES_DB=fxdb -e POSTGRES_USER=fxuser -e POSTGRES_PASSWORD=fxpass123 \
    -e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432 \
    -e SAVE_TO_MINIO=true -e MINIO_ENDPOINT=http://minio:9000 \
    -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin123 \
    -e MINIO_BUCKET=fx-raw \
    fxstack/forecast:any -u /app/train_any.py
}

# GRU/LSTM/ARIMA 각각 1,5,7일
for m in gru lstm arima; do
  for h in 1 5 7; do
    run_any "$m" "$h"
  done
done
