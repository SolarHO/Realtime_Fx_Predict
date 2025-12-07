#!/usr/bin/env bash
set -euo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LOG_DIR=/home/ssm-user/fx-stack/logs
mkdir -p "$LOG_DIR"
STAMP() { date '+%F %T %Z'; }
RUN() {
  local MODEL="$1"
  echo "[$(STAMP)] start $MODEL"
  /usr/bin/docker run --rm --network fx-stack_fxnet \
    --entrypoint python \
    -v /home/ssm-user/fx-stack/forecast_multi/train_any.py:/app/train_any.py:ro \
    -e MODEL="$MODEL" -e PAIR=USDKRW -e CTX=96 -e H=1 \
    -e EPOCHS=200 -e LR=1e-3 \
    -e POSTGRES_DB=fxdb -e POSTGRES_USER=fxuser -e POSTGRES_PASSWORD=fxpass123 \
    -e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432 \
    -e SAVE_TO_MINIO=true -e MINIO_ENDPOINT=http://minio:9000 \
    -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin123 \
    -e MINIO_BUCKET=fx-raw \
    fxstack/forecast:any -u /app/train_any.py
  echo "[$(STAMP)] done  $MODEL"
}
RUN arima
RUN lstm
