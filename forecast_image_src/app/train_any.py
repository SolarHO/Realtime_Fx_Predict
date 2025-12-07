import os, math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text

# ----------------- ENV -----------------
MODEL = os.getenv('MODEL','dlinear').lower()   # ex) dlinear, dlinearh5, dlinearh7, lstm, lstmh5, lstmh7, gru, gruh5, gruh7, arima, arimah5, arimah7
PAIR  = os.getenv('PAIR','USDKRW')
CTX   = int(os.getenv('CTX','96'))
H     = int(os.getenv('H','1'))

PG_USER = os.getenv("POSTGRES_USER","fxuser")
PG_PASS = os.getenv("POSTGRES_PASSWORD","fxpass123")
PG_DB   = os.getenv("POSTGRES_DB","fxdb")
PG_HOST = os.getenv("POSTGRES_HOST","postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT","5432"))

SAVE_TO_MINIO = os.getenv("SAVE_TO_MINIO","true").lower()=="true"
MINIO_EP   = os.getenv("MINIO_ENDPOINT","http://minio:9000")
MINIO_USER = os.getenv("MINIO_ROOT_USER","minioadmin")
MINIO_PASS = os.getenv("MINIO_ROOT_PASSWORD","minioadmin123")
MINIO_BUCKET=os.getenv("MINIO_BUCKET","fx-raw")

LR     = float(os.getenv("LR","1e-3"))
EPOCHS = int(os.getenv("EPOCHS","200"))

def get_engine():
    dsn = f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    return create_engine(dsn)

def load_series():
    sql = """
    SELECT kst_date, price
    FROM fx_features_daily
    WHERE pair = :pair
      AND price IS NOT NULL
    ORDER BY kst_date
    """
    df = pd.read_sql(text(sql), get_engine(), params={"pair": PAIR})
    df["kst_date"] = pd.to_datetime(df["kst_date"])
    return df

# ---------- SAVE: UPSERT H개 ----------

def save_pg(pred_dates, y_pred, last_true, model_label):
    """
    pred_dates : 예측된 kst_date 리스트 (datetime/date)
    y_pred     : 예측값 리스트/배열
    last_true  : 마지막 실제 환율 (y_true 용)
    model_label: MODEL 환경변수 값 (예: 'arima', 'lstmh5', 'gruh7' 등)
    """
    import os
    from datetime import datetime
    from math import isnan
    from sqlalchemy import MetaData, Table, Column, Date, String, Float, DateTime, text
    from sqlalchemy.dialects.postgresql import insert

    eng = get_engine()

    # H 값에 따라 어느 테이블에 쓸지 결정
    horizon = int(os.getenv("H", "1"))
    if horizon == 1:
        table_name = "fx_forecast_daily"
    elif horizon == 5:
        table_name = "fx_forecast_h5"
    elif horizon == 7:
        table_name = "fx_forecast_h7"
    else:
        # 나중에 10일, 30일 같은 거 추가할 때 쓸 확장용
        table_name = "fx_forecast_long"

    meta = MetaData()
    tbl = Table(
        table_name,
        meta,
        Column("kst_date", Date,    primary_key=True),
        Column("pair",     String,  primary_key=True),
        Column("model",    String,  primary_key=True),
        Column("y_pred",   Float),
        Column("y_true",   Float),
        Column("run_ts",   DateTime),
    )

    dates = list(pred_dates)
    preds = list(y_pred)

    with eng.begin() as conn:
        for d, y in zip(dates, preds):
            # 값이 이상하면 스킵
            try:
                y_val = float(y)
            except (TypeError, ValueError):
                continue
            if isnan(y_val):
                continue

            stmt = insert(tbl).values(
                kst_date=d,
                pair=PAIR,
                model=model_label,
                y_pred=y_val,
                y_true=float(last_true) if last_true is not None else None,
                run_ts=datetime.utcnow(),
            )

            # (kst_date, pair, model) 기준 UPSERT
            stmt = stmt.on_conflict_do_update(
                index_elements=["kst_date", "pair", "model"],
                set_={
                    "y_pred": stmt.excluded.y_pred,
                    "y_true": stmt.excluded.y_true,
                    "run_ts": text("NOW()"),
                },
            )
            conn.execute(stmt)


def make_dates(last_date, h):
    return [last_date + timedelta(days=i) for i in range(1, h+1)]

def split_mu_sigma(series, split_ratio=0.8):
    split = int(len(series)*split_ratio)
    mu = float(series[:split].mean())
    sigma = float(series[:split].std() + 1e-8)
    return mu, sigma

# ---------- Models ----------
def predict_arima(series, h):
    from statsmodels.tsa.arima.model import ARIMA
    model = ARIMA(series.values, order=(1,1,1))
    fit = model.fit()
    fc = fit.forecast(steps=h)
    return np.asarray(fc, dtype=float)

def predict_dlinear(series, h):
    # 간단 DLinear 스타일: 선형층로로 CTX 윈도우를 예측 (여기선 placeholder 형태)
    # 이미 이미지에 학습 루틴이 있을 수 있으니, 여기서는 roll-forward로 모사
    import torch, torch.nn as nn
    # 표준화
    mu, sigma = split_mu_sigma(series)
    s = (series - mu) / sigma
    # 학습 데이터
    X, y = [], []
    for i in range(CTX, len(s)):
        X.append(s.values[i-CTX:i])
        y.append(s.values[i])
    X = torch.tensor(np.array(X), dtype=torch.float32).unsqueeze(-1)
    y = torch.tensor(np.array(y), dtype=torch.float32)

    class DLinear(nn.Module):
        def __init__(self, ctx):
            super().__init__()
            self.fc = nn.Linear(ctx, 1)
        def forward(self, x):
            # x: [B,CTX,1] -> [B,1]
            return self.fc(x.squeeze(-1)).squeeze(-1)

    model = DLinear(CTX)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.MSELoss()

    n = len(X); n_tr = int(n*0.8)
    Xtr, ytr = X[:n_tr], y[:n_tr]
    Xva, yva = X[n_tr:], y[n_tr:]
    for e in range(1, EPOCHS+1):
        model.train(); opt.zero_grad()
        pred = model(Xtr)
        loss = loss_fn(pred, ytr)
        loss.backward(); opt.step()
    # 롤링 예측
    hist = s.values[-CTX:].astype(float).tolist()
    outs = []
    for _ in range(h):
        x = torch.tensor(np.array(hist[-CTX:])[None,:,None], dtype=torch.float32)
        with torch.no_grad():
            pn = model(x).item()
        yhat = pn * sigma + mu
        outs.append(yhat)
        hist.append(pn)  # 정규화 공간으로 이어붙임
    return np.array(outs, dtype=float)

def predict_rnn(series, h, cell="lstm"):
    import torch, torch.nn as nn
    mu, sigma = split_mu_sigma(series)
    s = (series - mu) / sigma

    X, y = [], []
    for i in range(CTX, len(s)):
        X.append(s.values[i-CTX:i])
        y.append(s.values[i])
    X = torch.tensor(np.array(X), dtype=torch.float32).unsqueeze(-1)
    y = torch.tensor(np.array(y), dtype=torch.float32)

    if cell=="lstm":
        RNN = nn.LSTM
    elif cell=="gru":
        RNN = nn.GRU
    else:
        raise ValueError("cell must be lstm or gru")

    class RNNModel(nn.Module):
        def __init__(self, hidden=32):
            super().__init__()
            self.rnn = RNN(input_size=1, hidden_size=hidden, batch_first=True)
            self.fc = nn.Linear(hidden, 1)
        def forward(self, x):
            out, _ = self.rnn(x)
            out = self.fc(out[:,-1,:])
            return out.squeeze(-1)

    model = RNNModel()
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.MSELoss()

    n = len(X); n_tr = int(n*0.8)
    Xtr, ytr = X[:n_tr], y[:n_tr]
    Xva, yva = X[n_tr:], y[n_tr:]

    for e in range(1, EPOCHS+1):
        model.train(); opt.zero_grad()
        pred = model(Xtr)
        loss = loss_fn(pred, ytr)
        loss.backward(); opt.step()
        if e % 20 == 0:
            model.eval()
            with torch.no_grad():
                pv = model(Xva)
                ve = loss_fn(pv, yva).item()
                # print(f"[{cell}] epoch={e:03d} val={ve:.6f}")

    # 롤링 예측
    hist = s.values[-CTX:].astype(float).tolist()
    outs = []
    for _ in range(h):
        x = torch.tensor(np.array(hist[-CTX:])[None,:,None], dtype=torch.float32)
        with torch.no_grad():
            pn = model(x).item()  # 정규화 공간
        yhat = pn * sigma + mu
        outs.append(yhat)
        hist.append(pn)
    return np.array(outs, dtype=float)

# ---------- Main ----------
def main():
    # MODEL에서 베이스/지평 추출
    base = MODEL
    horizon = H
    for tag in ("h5","h7"):
        if MODEL.endswith(tag):
            base = MODEL[:-len(tag)]
            horizon = int(tag[1:])  # 'h5'->5, 'h7'->7
            break

    df = load_series()
    series = df["price"]
    last_true = float(series.iloc[-1])
    last_date = df["kst_date"].iloc[-1]
    pred_dates = make_dates(last_date, horizon)

    # 분기
    if base == "dlinear":
        y_pred = predict_dlinear(series, horizon)
    elif base == "lstm":
        y_pred = predict_rnn(series, horizon, cell="lstm")
    elif base == "gru":
        y_pred = predict_rnn(series, horizon, cell="gru")
    elif base == "arima":
        y_pred = predict_arima(series, horizon)
    else:
        raise ValueError(f"unsupported MODEL base: {base}")

    # 저장 + CSV
    save_pg(pred_dates, y_pred, last_true, model_label=MODEL)
    out = pd.DataFrame({"kst_date": pred_dates, "pair": PAIR, "model": MODEL, "y_true": last_true, "y_pred": y_pred})
    out.to_csv("/tmp/forecast.csv", index=False)
    upload_minio("/tmp/forecast.csv", MODEL)
    print(f"[done] {MODEL} saved {len(out)} preds for {PAIR}")



def upload_minio(local_csv, model_label):
    """
    MinIO로 forecast CSV 업로드
    (train_any.py 전용: 모델 라벨을 인자로 받아서 파일명에 반영)
    """
    import os, datetime as dt
    from dateutil.tz import gettz
    try:
        today = dt.datetime.now(gettz("Asia/Seoul")).strftime("%Y/%m/%d")
        key = f"{today}/forecast_{PAIR}_{model_label}.csv"
        print(f"[minio-tip] {local_csv} -> s3://{MINIO_BUCKET}/{key}")
        os.system(
            f"mc alias set local {MINIO_EP} {MINIO_USER} {MINIO_PASS} >/dev/null 2>&1 || true && "
            f"mc cp {local_csv} local/{MINIO_BUCKET}/{key} >/dev/null 2>&1 || true"
        )
    except Exception as e:
        print("[minio] skip:", e)

if __name__ == "__main__":
    main()


def upload_minio(local_csv, model_label):
    """
    MinIO로 forecast CSV 업로드 (train_dlinear.py와 비슷한 방식)
    """
    import os, datetime as dt
    from dateutil.tz import gettz
    try:
        today = dt.datetime.now(gettz("Asia/Seoul")).strftime("%Y/%m/%d")
        key = f"{today}/forecast_{PAIR}_{model_label}.csv"
        print(f"[minio-tip] {local_csv} -> s3://{MINIO_BUCKET}/{key}")
        os.system(
            f"mc alias set local {MINIO_EP} {MINIO_USER} {MINIO_PASS} >/dev/null 2>&1 || true && "
            f"mc cp {local_csv} local/{MINIO_BUCKET}/{key} >/dev/null 2>&1 || true"
        )
    except Exception as e:
        print("[minio] skip:", e)
