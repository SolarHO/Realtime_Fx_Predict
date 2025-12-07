#!/usr/bin/env bash
set -euo pipefail
NET=fx-stack_fxnet IMG=fxstack/forecast:any PAIR=USDKRW CTX=96 EPOCHS=200 LR=1e-3
PG="-e POSTGRES_DB=fxdb -e POSTGRES_USER=fxuser -e POSTGRES_PASSWORD=fxpass123 -e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432"
S3="-e SAVE_TO_MINIO=true -e MINIO_ENDPOINT=http://minio:9000 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin123 -e MINIO_BUCKET=fx-raw"
run(){ docker run --rm --network "$NET" -e MODEL="$1" -e PAIR="$PAIR" -e CTX="$CTX" -e H="$2" -e EPOCHS="$EPOCHS" -e LR="$LR" $PG $S3 "$IMG"; }
# 5일
run dlinearh5 5; run gruh5 5; run lstmh5 5; run arimah5 5
# 7일
run dlinearh7 7; run gruh7 7; run lstmh7 7; run arimah7 7
