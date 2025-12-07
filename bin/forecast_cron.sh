#!/usr/bin/env bash
set -euo pipefail

LOG_DIR=/home/ssm-user/fx-stack/logs
mkdir -p "$LOG_DIR"
STAMP=$(date +%Y%m)

# 로그 리다이렉션
exec >>"$LOG_DIR/forecast_${STAMP}.log" 2>&1

# 실제 실행
/usr/bin/docker run --rm --network fx-stack_fxnet \
  -e PAIR=USDKRW -e CTX=96 -e H=1 \
  -e EPOCHS=200 -e LR=1e-3 \
  -e POSTGRES_DB=fxdb -e POSTGRES_USER=fxuser -e POSTGRES_PASSWORD=fxpass123 \
  -e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432 \
  -e SAVE_TO_MINIO=true \
  -e MINIO_ENDPOINT=http://minio:9000 \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin123 \
  -e MINIO_BUCKET=fx-raw \
  fxstack/forecast:dlinear
