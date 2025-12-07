#!/usr/bin/env bash
set -euo pipefail

# fx-stack 루트로 이동
cd "$(dirname "$0")/.."

NET="fx-stack_fxnet"
IMG="fxstack/forecast:any"

FORECAST_APP="$PWD/forecast_image_src/app"

# Postgres / MinIO 기본값 (docker-compose랑 맞게)
PG_ENV_OPTS="
  -e POSTGRES_USER=${POSTGRES_USER:-fxuser}
  -e POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-fxpass123}
  -e POSTGRES_DB=${POSTGRES_DB:-fxdb}
  -e POSTGRES_HOST=${POSTGRES_HOST:-postgres}
  -e POSTGRES_PORT=${POSTGRES_PORT:-5432}
"

S3_ENV_OPTS="
  -e MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://minio:9000}
  -e MINIO_ROOT_USER=${MINIO_ROOT_USER:-minioadmin}
  -e MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD:-minioadmin123}
  -e MINIO_BUCKET=${MINIO_BUCKET:-fx-raw}
"

PAIR="${PAIR:-USDKRW}"
CTX="${CTX:-96}"
EPOCHS="${EPOCHS:-200}"
LR="${LR:-1e-3}"

log() {
  echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"
}

run_dlinear() {
  local h="$1"
  log "start dlinear (H=${h})"
  docker run --rm --network "${NET}" \
    -v "${FORECAST_APP}":/app \
    ${PG_ENV_OPTS} ${S3_ENV_OPTS} \
    -e MODEL="dlinear" -e PAIR="${PAIR}" -e CTX="${CTX}" -e H="${h}" \
    -e EPOCHS="${EPOCHS}" -e LR="${LR}" \
    "${IMG}"
  log "done  dlinear (H=${h})"
}

run_any() {
  local model="$1"
  local h="$2"
  log "start ${model} (H=${h})"
  docker run --rm --network "${NET}" \
    --entrypoint python \
    -v "${FORECAST_APP}":/app \
    ${PG_ENV_OPTS} ${S3_ENV_OPTS} \
    -e MODEL="${model}" -e PAIR="${PAIR}" -e CTX="${CTX}" -e H="${h}" \
    -e EPOCHS="${EPOCHS}" -e LR="${LR}" \
    "${IMG}" train_any.py
  log "done  ${model} (H=${h})"
}

log "=== forecast_all_horizons.sh start ==="

# H = 1 (하루치)
run_dlinear 1
run_any arima 1
run_any lstm 1
run_any gru 1

# H = 5 (5일치)
run_dlinear 5       # dlinear 5일치
run_any lstmh5 5
run_any gruh5 5
run_any arimah5 5

# H = 7 (7일치)
run_dlinear 7       # dlinear 7일치
run_any lstmh7 7
run_any gruh7 7
run_any arimah7 7

log "=== forecast_all_horizons.sh done ==="
