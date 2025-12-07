import os, math, datetime as dt
import numpy as np, pandas as pd
from dateutil.tz import gettz
from sqlalchemy import create_engine, text
import torch, torch.nn as nn

PAIR   = os.getenv("PAIR",  "USDKRW")
CTX    = int(os.getenv("CTX", "96"))    # 입력 윈도우 길이(96일)
HORIZ  = int(os.getenv("H",   "1"))     # 예측 일수(1일=다음날)
EPOCHS = int(os.getenv("EPOCHS", "200"))
LR     = float(os.getenv("LR", "1e-3"))
MODEL  = "dlinear"

PG_USER = os.getenv("POSTGRES_USER","fxuser")
PG_PASS = os.getenv("POSTGRES_PASSWORD","fxpass123")
PG_DB   = os.getenv("POSTGRES_DB","fxdb")
PG_HOST = os.getenv("POSTGRES_HOST","postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT","5432"))

MINIO_ON   = os.getenv("SAVE_TO_MINIO","true").lower()=="true"
MINIO_EP   = os.getenv("MINIO_ENDPOINT","http://minio:9000")
MINIO_USER = os.getenv("MINIO_ROOT_USER","minioadmin")
MINIO_PASS = os.getenv("MINIO_ROOT_PASSWORD","minioadmin123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET","fx-raw")

# --- dLinear (아주 단순화한 일변량 버전) ---
class DLinear(nn.Module):
    def __init__(self, seq_len, pred_len):
        super().__init__()
        self.seq_len  = seq_len
        self.pred_len = pred_len
        self.linear   = nn.Linear(seq_len, pred_len)

    def forward(self, x):            # x: [B, seq_len]
        return self.linear(x)        # -> [B, pred_len]

def get_engine():
    uri = f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    return create_engine(uri, pool_pre_ping=True)

def load_series():
    sql = """
    SELECT kst_date, price
    FROM fx_features_daily
    WHERE pair = :pair
      AND price IS NOT NULL
    ORDER BY kst_date
    """
    df = pd.read_sql(text(sql), get_engine(), params={"pair": PAIR})
    return df

def make_ds(values, ctx, horizon):
    X, Y = [], []
    for i in range(len(values) - ctx - horizon + 1):
        X.append(values[i:i+ctx])
        Y.append(values[i+ctx:i+ctx+horizon])
    X = np.asarray(X, dtype=np.float32); Y = np.asarray(Y, dtype=np.float32)
    return torch.from_numpy(X), torch.from_numpy(Y)

def save_pg(dates, y_pred, last_true):
    """DLinear 예측을 Postgres에 UPSERT"""
    import os
    from datetime import datetime
    from math import isnan
    from sqlalchemy import MetaData, Table, Column, Date, String, Float, DateTime, text
    from sqlalchemy.dialects.postgresql import insert

    eng = get_engine()

    # horizon(H)에 따라 테이블 선택
    horizon = int(os.getenv("H", "1"))
    if horizon == 1:
        table_name = "fx_forecast_daily"
    elif horizon == 5:
        table_name = "fx_forecast_h5"
    elif horizon == 7:
        table_name = "fx_forecast_h7"
    else:
        table_name = "fx_forecast_long"

    meta = MetaData()
    tbl = Table(
        table_name,
        meta,
        Column("kst_date", Date, primary_key=True),
        Column("pair", String, primary_key=True),
        Column("model", String, primary_key=True),
        Column("y_pred", Float),
        Column("y_true", Float),
        Column("run_ts", DateTime),
    )

    ds = list(dates)
    preds = list(y_pred)

    with eng.begin() as conn:
        for d, y in zip(ds, preds):
            try:
                y_val = float(y)
            except (TypeError, ValueError):
                continue
            if isnan(y_val):
                continue

            stmt = insert(tbl).values(
                kst_date=d.date() if hasattr(d, "date") else d,
                pair=PAIR,
                model=MODEL,
                y_pred=y_val,
                y_true=float(last_true) if last_true is not None else None,
                run_ts=datetime.utcnow(),
            )

            stmt = stmt.on_conflict_do_update(
                index_elements=["kst_date", "pair", "model"],
                set_={
                    "y_pred": stmt.excluded.y_pred,
                    "y_true": stmt.excluded.y_true,
                    "run_ts": text("NOW()"),
                },
            )
            conn.execute(stmt)


def save_minio_csv(pred_dates, y_pred):
    try:
        import io, requests, csv, datetime as dt
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["kst_date","pair","y_pred","model"])
        for d,v in zip(pred_dates, y_pred):
            w.writerow([d.isoformat(), PAIR, f"{v:.6f}", MODEL])
        today = dt.datetime.now(gettz("Asia/Seoul")).strftime("%Y/%m/%d")
        key = f"{today}/forecast_{PAIR}_{MODEL}.csv"
        open("/tmp/forecast.csv","w").write(buf.getvalue())
        print(f"[minio-tip] /tmp/forecast.csv -> s3://{MINIO_BUCKET}/{key}")
    except Exception as e:
        print("[minio] skip:", e)

def main():
    df = load_series()
    if len(df) < CTX + HORIZ + 30:
        raise RuntimeError(f"too short series: {len(df)} rows")

    vals = df["price"].values.astype(np.float32)
    # 표준화(스케일): train 구간 평균/표준편차
    mean, std = vals.mean(), vals.std() + 1e-8
    z = (vals - mean) / std

    X, Y = make_ds(z, CTX, HORIZ)
    # 전 구간 학습
    n = len(X)
    tr = max(int(n*0.8), 1)
    Xtr, Ytr = X[:tr], Y[:tr]
    Xva, Yva = X[tr:], Y[tr:]

    model = DLinear(CTX, HORIZ)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.MSELoss()

    model.train()
    for epoch in range(EPOCHS):
        opt.zero_grad()
        yhat = model(Xtr).squeeze()
        loss = loss_fn(yhat, Ytr.squeeze())
        loss.backward()
        opt.step()
        if len(Xva)>0 and (epoch+1)%20==0:
           model.eval()
           with torch.no_grad():
               yva = model(Xva).squeeze()
               va_mse = loss_fn(yva, Yva.squeeze()).item()
               # 역스케일 기준 MAE/MAPE 출력
               yva_np  = yva.cpu().numpy() * std + mean
               ytrue_np= Yva.squeeze().cpu().numpy() * std + mean
               mae = float(np.mean(np.abs(yva_np - ytrue_np)))
               mape = float(np.mean(np.abs((yva_np - ytrue_np)/(ytrue_np+1e-8)))*100)
           model.train()
           print(f"[val] epoch={epoch+1} MSE={va_mse:.6f}  MAE={mae:.6f}  MAPE={mape:.2f}%")

    # 마지막 구간으로 예측
    x_last = torch.from_numpy(z[-CTX:].copy()).unsqueeze(0)  # [1, CTX]
    model.eval()
    with torch.no_grad():
        yhat = model(x_last).cpu().numpy()[0]
    # 역스케일
    y_pred = (yhat * std) + mean

    # 예측 날짜들
    last_date = pd.to_datetime(df["kst_date"].iloc[-1]).date()
    pred_dates = [last_date + pd.Timedelta(days=i) for i in range(1, HORIZ+1)]

    # 저장
    save_pg(pred_dates, y_pred, last_true=df["price"].iloc[-1])
    if MINIO_ON:
        save_minio_csv(pred_dates, y_pred)
    print(f"[done] saved {len(pred_dates)} preds for {PAIR}")

if __name__ == "__main__":
    main()
