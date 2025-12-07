import os, math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text, DateTime, func

def _ensure_run_ts(rows):
    """Ensure every row has non-null run_ts using func.now()."""
    try:
        from sqlalchemy import func  # local import to be safe
    except Exception:
        func = None
    def set_now(d):
        if d is None:
            return
        if 'run_ts' not in d or d['run_ts'] is None:
            d['run_ts'] = func.now() if func is not None else None
    if isinstance(rows, dict):
        set_now(rows)
    elif isinstance(rows, list):
        for r in rows:
            set_now(r)
    return rows



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
    pred_dates : list[date/datetime]  예측 날짜들
    y_pred    : list[float]           예측값들
    last_true : float|None            최근 실측
    model_label : str                 저장할 모델 라벨 (예: 'dlinearh5')
    """
    import math
    from sqlalchemy import MetaData, Table, Column, Date, String, Float, DateTime, func
    from sqlalchemy.dialects.postgresql import insert

    # 대상 테이블 자동 선택
    table_name = target_table(model_label, H)

    eng = get_engine()

    rows = []
    for d, y in zip(pred_dates, y_pred):
        rows.append({
            "kst_date": d.date() if hasattr(d, "date") else d,
            "pair": PAIR,
            "model": model_label,
            "y_true": float(last_true) if (last_true is not None and not (isinstance(last_true, float) and math.isnan(last_true))) else None,
            "y_pred": float(y) if (y is not None and not (isinstance(y, float) and math.isnan(y))) else None,
            "yhat_lo": None,
            "yhat_hi": None,
            "run_ts": None,  # server_default 및 upsert에서 갱신
        })

    meta = MetaData()
    tbl = Table(
        table_name, meta,
        Column('kst_date', Date, primary_key=True),
        Column('pair',     String, primary_key=True),
        Column('model',    String, primary_key=True),
        Column('y_true',   Float),
        Column('y_pred',   Float),
        Column('yhat_lo',  Float),
        Column('yhat_hi',  Float),
        Column('run_ts',   DateTime(timezone=True), server_default=func.now()),
    )

    stmt = insert(tbl)
    upsert = stmt.on_conflict_do_update(
        index_elements=['kst_date','pair','model'],
        set_={
            'y_true' : stmt.excluded.y_true,
            'y_pred' : stmt.excluded.y_pred,
            'yhat_lo': stmt.excluded.yhat_lo,
            'yhat_hi': stmt.excluded.yhat_hi,
            'run_ts' : func.now(),
        }
    )

    with eng.begin() as conn:
        rows = _ensure_run_ts(rows)

        conn.execute(upsert.values(rows))

def target_table(model: str, H: int) -> str:
    m = (model or "").lower()
    if m.endswith("h5") or H == 5:
        return "fx_forecast_h5"
    if m.endswith("h7") or H == 7:
        return "fx_forecast_h7"
    return "fx_forecast_daily"

def upload_minio(local_csv, model_label):
    if not SAVE_TO_MINIO: return
    today = datetime.utcnow().astimezone().strftime("%Y/%m/%d")
    key = f"{today}/forecast_{PAIR}_{model_label}.csv"
    os.system(
        f"mc alias set local {MINIO_EP} {MINIO_USER} {MINIO_PASS} >/dev/null 2>&1 || true && "
        f"echo \"[minio-tip] {local_csv} -> s3://{MINIO_BUCKET}/{key}\" && "
        f"mc cp {local_csv} local/{MINIO_BUCKET}/{key} >/dev/null 2>&1 || true"
    )

# ---------- Helpers ----------
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

if __name__ == "__main__":
    main()
