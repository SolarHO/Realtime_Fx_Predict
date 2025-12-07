-- 1) 테이블: 하루치(기존), 5일치, 7일치 (스키마 동일)
CREATE TABLE IF NOT EXISTS fx_forecast_h5 (
  kst_date date NOT NULL,
  pair     text NOT NULL,
  model    text NOT NULL,
  y_true   double precision,
  y_pred   double precision,
  yhat_lo  double precision,
  yhat_hi  double precision,
  run_ts   timestamptz DEFAULT now(),
  PRIMARY KEY (kst_date, pair, model)
);

CREATE TABLE IF NOT EXISTS fx_forecast_h7 (
  kst_date date NOT NULL,
  pair     text NOT NULL,
  model    text NOT NULL,
  y_true   double precision,
  y_pred   double precision,
  yhat_lo  double precision,
  yhat_hi  double precision,
  run_ts   timestamptz DEFAULT now(),
  PRIMARY KEY (kst_date, pair, model)
);

-- 2) “오늘 최신 실행분만” 보이게 하는 뷰 (모델별·쌍별로 최신 run_ts만 노출)
--   * 필요 시 CURRENT_DATE 대신 원하는 기준일로 바꿔도 됨
CREATE OR REPLACE VIEW fx_forecast_h5_latest AS
WITH last_run AS (
  SELECT pair, MAX(run_ts) AS max_run_ts
  FROM fx_forecast_h5
  WHERE kst_date >= CURRENT_DATE       -- 오늘/미래 예측만
  GROUP BY pair
)
SELECT f.*
FROM fx_forecast_h5 f
JOIN last_run r
  ON f.pair=r.pair AND f.run_ts=r.max_run_ts
WHERE f.kst_date >= CURRENT_DATE;

CREATE OR REPLACE VIEW fx_forecast_h7_latest AS
WITH last_run AS (
  SELECT pair, MAX(run_ts) AS max_run_ts
  FROM fx_forecast_h7
  WHERE kst_date >= CURRENT_DATE
  GROUP BY pair
)
SELECT f.*
FROM fx_forecast_h7 f
JOIN last_run r
  ON f.pair=r.pair AND f.run_ts=r.max_run_ts
WHERE f.kst_date >= CURRENT_DATE;

-- 3) 피벗 뷰 (Superset에서 라인 여러 개로 보기 좋게)
--    필요 모델명만 추가/제거 가능
CREATE OR REPLACE VIEW fx_forecast_h5_latest_pivot AS
SELECT
  pair,
  MAX(CASE WHEN model='dlinearh5' THEN y_pred END) AS yhat_dlinearh5,
  MAX(CASE WHEN model='gruh5'     THEN y_pred END) AS yhat_gruh5,
  MAX(CASE WHEN model='lstmh5'    THEN y_pred END) AS yhat_lstmh5,
  MAX(CASE WHEN model='arimah5'   THEN y_pred END) AS yhat_arimah5,
  kst_date
FROM fx_forecast_h5_latest
GROUP BY pair, kst_date
ORDER BY kst_date;

CREATE OR REPLACE VIEW fx_forecast_h7_latest_pivot AS
SELECT
  pair,
  MAX(CASE WHEN model='dlinearh7' THEN y_pred END) AS yhat_dlinearh7,
  MAX(CASE WHEN model='gruh7'     THEN y_pred END) AS yhat_gruh7,
  MAX(CASE WHEN model='lstmh7'    THEN y_pred END) AS yhat_lstmh7,
  MAX(CASE WHEN model='arimah7'   THEN y_pred END) AS yhat_arimah7,
  kst_date
FROM fx_forecast_h7_latest
GROUP BY pair, kst_date
ORDER BY kst_date;

-- 4) 검증용 집계 뷰
CREATE OR REPLACE VIEW fx_forecast_h_counts AS
SELECT 'h5' AS bucket, model, COUNT(*) AS rows, MIN(kst_date) AS min_d, MAX(kst_date) AS max_d
FROM fx_forecast_h5 GROUP BY model
UNION ALL
SELECT 'h7' AS bucket, model, COUNT(*) AS rows, MIN(kst_date) AS min_d, MAX(kst_date) AS max_d
FROM fx_forecast_h7 GROUP BY model
ORDER BY bucket, model;
