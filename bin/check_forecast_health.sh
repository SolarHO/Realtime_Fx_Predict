#!/usr/bin/env bash
set -euo pipefail

PAIR="${1:-USDKRW}"     # 사용법: check_forecast_health.sh [PAIR]
PG="psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1 -F $'\t' -A -q -X -P pager=off"

run_sql () {
  docker exec -i postgres bash -lc "$PG -c \"$1\""
}

echo "=== [1] 전체 건수 (pair=${PAIR}) ========================================="
run_sql "
SELECT 'fx_forecast_daily' AS tbl, COUNT(*) AS rows
  FROM fx_forecast_daily WHERE pair='${PAIR}'
UNION ALL
SELECT 'fx_forecast_h5'   , COUNT(*) FROM fx_forecast_h5    WHERE pair='${PAIR}'
UNION ALL
SELECT 'fx_forecast_h7'   , COUNT(*) FROM fx_forecast_h7    WHERE pair='${PAIR}'
ORDER BY 1;"

echo
echo "=== [2] 테이블별 모델 분포/기간 ========================================="
for T in fx_forecast_daily fx_forecast_h5 fx_forecast_h7; do
  echo "-- ${T}"
  run_sql "
  SELECT model, COUNT(*) AS rows, MIN(kst_date) AS min_d, MAX(kst_date) AS max_d
  FROM ${T}
  WHERE pair='${PAIR}'
  GROUP BY model
  ORDER BY model;"
done

echo
echo "=== [3] 최근 20건(run_ts순) 샘플 ========================================"
for T in fx_forecast_daily fx_forecast_h5 fx_forecast_h7; do
  echo "-- ${T}"
  run_sql "
  SELECT run_ts, kst_date, model, y_pred
  FROM ${T}
  WHERE pair='${PAIR}'
  ORDER BY run_ts DESC
  LIMIT 20;"
done

echo
echo "=== [4] 중복 키 점검(동일 kst_date,pair,model가 2건 이상) ================="
for T in fx_forecast_daily fx_forecast_h5 fx_forecast_h7; do
  echo "-- ${T}"
  run_sql "
  SELECT kst_date, model, COUNT(*) AS dup_cnt
  FROM ${T}
  WHERE pair='${PAIR}'
  GROUP BY kst_date, model
  HAVING COUNT(*)>1
  ORDER BY kst_date DESC, model;"
done

echo
echo "=== [5] 최근 14일 커버리지(일일예측: 존재=1/부재=0) ======================"
run_sql "
WITH cal AS (
  SELECT generate_series(current_date-13, current_date, '1 day')::date AS kst_date
)
SELECT c.kst_date,
       MAX(CASE WHEN f.model='dlinear' THEN 1 ELSE 0 END) AS has_dlinear,
       MAX(CASE WHEN f.model='arima'   THEN 1 ELSE 0 END) AS has_arima,
       MAX(CASE WHEN f.model='lstm'    THEN 1 ELSE 0 END) AS has_lstm,
       MAX(CASE WHEN f.model='gru'     THEN 1 ELSE 0 END) AS has_gru
FROM cal c
LEFT JOIN fx_forecast_daily f
  ON f.pair='${PAIR}' AND f.kst_date=c.kst_date
GROUP BY c.kst_date
ORDER BY c.kst_date DESC;"

echo
echo "=== [6] 오늘 최신 뷰(h5/h7_latest) 확인 ==================================="
echo "-- fx_forecast_h5_latest"
run_sql "SELECT kst_date, model, y_pred FROM fx_forecast_h5_latest WHERE pair='${PAIR}' ORDER BY kst_date, model;"
echo "-- fx_forecast_h7_latest"
run_sql "SELECT kst_date, model, y_pred FROM fx_forecast_h7_latest WHERE pair='${PAIR}' ORDER BY kst_date, model;"

echo
echo "=== [7] 오늘 업로드 파일 유무(선택: MinIO) ================================"
# MinIO 클라이언트(mc)가 컨테이너에 있을 때만 유효
# 오늘 날짜 폴더에 forecast_파일 존재 여부 확인
docker run --rm --network fx-stack_fxnet --entrypoint /bin/sh minio/mc -c "
mc alias set local http://minio:9000 ${MINIO_ROOT_USER:-minioadmin} ${MINIO_ROOT_PASSWORD:-minioadmin123} >/dev/null 2>&1 || true
DATE=\$(TZ=Asia/Seoul date +%Y/%m/%d)
mc ls local/${MINIO_BUCKET:-fx-raw}/\${DATE}/ 2>/dev/null | sed -n \"/forecast_${PAIR}_/p\" || true
" || true

echo
echo "Done."
