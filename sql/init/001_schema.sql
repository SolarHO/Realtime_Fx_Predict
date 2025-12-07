CREATE TABLE IF NOT EXISTS fx_rates (
  ts timestamptz PRIMARY KEY,
  pair text NOT NULL,
  price numeric(12,6) NOT NULL
);
CREATE TABLE IF NOT EXISTS fx_features (
  ts timestamptz PRIMARY KEY,
  dollar_index numeric(10,4),
  nasdaq numeric(12,2),
  us10y numeric(10,4),
  gold numeric(12,2)
);
CREATE TABLE IF NOT EXISTS fx_predict (
  ts timestamptz PRIMARY KEY,
  pred_price numeric(12,6) NOT NULL,
  model text DEFAULT 'dlinear'
);
CREATE OR REPLACE VIEW v_fx_all AS
SELECT r.ts, r.price, f.dollar_index, f.nasdaq, f.us10y, f.gold, p.pred_price
FROM fx_rates r
LEFT JOIN fx_features f ON f.ts = r.ts
LEFT JOIN fx_predict  p ON p.ts = r.ts;
