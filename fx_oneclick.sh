#!/usr/bin/env bash
set -euo pipefail

ROOT=~/fx-stack
cd "$ROOT"

echo "==[0/6] 환경 점검 =="
command -v docker >/dev/null || { echo "docker 필요"; exit 1; }
command -v docker compose >/dev/null || { echo "docker compose 필요"; exit 1; }

# Alpha Vantage 키가 override에 들어가 있거나 환경에 있어야 함
ALPHA_IN_ENV="${ALPHAVANTAGE_KEY:-}"
if [ -z "$ALPHA_IN_ENV" ]; then
  echo "참고: ALPHAVANTAGE_KEY 환경변수가 비어있습니다. docker-compose.override.yml에 설정되어 있어야 합니다."
fi

echo "==[1/6] yf_daily 재배포 (이미지/환경 반영) =="
docker compose up -d --no-deps --force-recreate yf_daily

echo "==[2/6] 수집 헬스 로그 확인 (오늘 09:00 KST 이후) =="
SINCE=$(TZ=Asia/Seoul date -d 'today 09:00' +%Y-%m-%dT%H:%M:%S%:z)
docker logs yf_daily --since "$SINCE" | egrep '\[ok\]|\[done\]|\[minio\]|\[yahoo-fail\]|error|fatal' || true

echo "==[3/6] Postgres 뷰 생성: fx_daily_latest =="
docker exec -i postgres bash -lc "psql -U \$POSTGRES_USER -d \$POSTGRES_DB" <<'SQL'
CREATE OR REPLACE VIEW fx_daily_latest AS
SELECT DISTINCT ON (date_trunc('day', ts AT TIME ZONE 'Asia/Seoul'), pair)
       date_trunc('day', ts AT TIME ZONE 'Asia/Seoul')::date AS kst_date,
       pair, price, ts
FROM fx_rates
ORDER BY date_trunc('day', ts AT TIME ZONE 'Asia/Seoul'), pair, ts DESC;
SQL

echo "==[4/6] MinIO 보존정책(ILM) 180일 설정 =="
docker run --rm --network fx-stack_fxnet --entrypoint /bin/sh minio/mc -c "
mc alias set local http://minio:9000 minioadmin minioadmin123 &&
mc ilm add --expire-days 180 local/fx-raw || true &&
mc mb --ignore-existing local/fx-raw/backups || true
"

echo "==[5/6] Postgres 스냅샷 생성 및 MinIO 업로드 =="
STAMP=$(date -u +%F)
docker exec -it postgres bash -lc "pg_dump -U \$POSTGRES_USER -d \$POSTGRES_DB -Fc -f /tmp/fxdb_${STAMP}.dump && ls -lh /tmp/fxdb_${STAMP}.dump"
docker cp postgres:/tmp/fxdb_${STAMP}.dump "${ROOT}/"
docker run --rm --network fx-stack_fxnet -v "${ROOT}:/backup" --entrypoint /bin/sh minio/mc -c "
mc alias set local http://minio:9000 minioadmin minioadmin123 &&
mc cp /backup/fxdb_${STAMP}.dump local/fx-raw/backups/
"

echo "==[6/6] 최근 180일 USDKRW CSV 추출 =="
docker exec -i postgres bash -lc "psql -U \$POSTGRES_USER -d \$POSTGRES_DB" <<'SQL'
\copy (
  SELECT kst_date, price
  FROM fx_daily_latest
  WHERE pair='USDKRW'
    AND kst_date >= (now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '180 days'
  ORDER BY kst_date
) TO '/tmp/usdkrw_180d.csv' WITH CSV HEADER;
SQL
docker cp postgres:/tmp/usdkrw_180d.csv "${ROOT}/"

echo ""
echo "=== 완료 요약 ==="
echo "- yf_daily 재배포 완료"
echo "- 뷰 fx_daily_latest 생성/갱신 완료"
echo "- MinIO 보존정책(180일) 적용"
echo "- Postgres 스냅샷: ${ROOT}/fxdb_${STAMP}.dump (MinIO backups에도 업로드)"
echo "- 최근 180일 CSV: ${ROOT}/usdkrw_180d.csv"
echo ""
echo "대시보드 권장:"
echo "  Superset(http://<EC2>:8088) 에서 Dataset=fx_daily_latest -> Line 차트 생성 (Time=kst_date, Metric=avg(price), Filter=pair='USDKRW')."
