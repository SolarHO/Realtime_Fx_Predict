import os, math, datetime as dt
import numpy as np, pandas as pd
import torch, torch.nn as nn
from sqlalchemy import create_engine, text, MetaData, Table, Column, Date, String, Float
from sqlalchemy.dialects.postgresql import insert

PAIR   = os.getenv("PAIR","USDKRW")
CTX    = int(os.getenv("CTX","96"))
HORIZ  = int(os.getenv("H","1"))
MODEL  = os.getenv("MODEL","dlinear").lower()  # dlinear|arima|lstm

PG_USER = os.getenv("POSTGRES_USER","fxuser")
PG_PASS = os.getenv("POSTGRES_PASSWORD","fxpass123")
PG_DB   = os.getenv("POSTGRES_DB","fxdb")
PG_HOST = os.getenv("POSTGRES_HOST","postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT","5432"))

SAVE_TO_MINIO = os.getenv("SAVE_TO_MINIO","false").lower()=="true"
MINIO_EP   = os.getenv("MINIO_ENDPOINT","http://minio:9000")
MINIO_USER = os.getenv("MINIO_ROOT_USER","minioadmin")
MINIO_PASS = os.getenv("MINIO_ROOT_PASSWORD","minioadmin123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET","fx-raw")

def get_engine():
    uri=f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    return create_engine(uri)

def load_series():
    sql = """
      SELECT kst_date, price
      FROM fx_features_daily
      WHERE pair = :pair AND price IS NOT NULL
      ORDER BY kst_date
    """
    df = pd.read_sql(text(sql), get_engine(), params={"pair": PAIR})
    return df

def upsert_forecast(dates, y_pred, last_true):
    engine = get_engine()
    meta = MetaData()
    tbl = Table('fx_forecast_daily', meta,
        Column('kst_date', Date, primary_key=True),
        Column('pair', String, primary_key=True),
        Column('model', String, primary_key=True),
        Column('y_true', Float),
        Column('y_pred', Float),
        Column('yhat_lo', Float),
        Column('yhat_hi', Float),
    )
    rows=[]
    for d, y in zip(dates, y_pred):
        rows.append({
            "kst_date": d.date() if hasattr(d,"date") else d,
            "pair": PAIR, "model": MODEL,
            "y_true": float(last_true) if last_true is not None and not (isinstance(last_true,float) and math.isnan(last_true)) else None,
            "y_pred": float(y) if y is not None and not (isinstance(y,float) and math.isnan(y)) else None,
            "yhat_lo": None, "yhat_hi": None,
        })
    stmt = insert(tbl).values(rows)
    upsert = stmt.on_conflict_do_update(
        index_elements=['kst_date','pair','model'],
        set_={
            'y_true': stmt.excluded.y_true,
            'y_pred': stmt.excluded.y_pred,
            'yhat_lo': stmt.excluded.yhat_lo,
            'yhat_hi': stmt.excluded.yhat_hi,
        }
    )
    with engine.begin() as conn:
        conn.execute(upsert)

def save_minio_csv(dates, preds):
    if not SAVE_TO_MINIO: return
    import pandas as pd, os, subprocess, tempfile
    df = pd.DataFrame({"kst_date":dates, "pair":PAIR, "model":MODEL, "y_pred":preds})
    tmp = "/tmp/forecast.csv"
    df.to_csv(tmp, index=False)
    y=dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime("%Y")
    m=dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime("%m")
    d=dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime("%d")
    key = f"{y}/{m}/{d}/forecast_{PAIR}_{MODEL}.csv"
    print(f"[minio-tip] {tmp} -> s3://{MINIO_BUCKET}/{key}")
    cmd = ["mc","alias","set","local",MINIO_EP,MINIO_USER,MINIO_PASS,"&&",
           "mc","cp",tmp,f"local/{MINIO_BUCKET}/{key}"]
    os.system(" ".join(cmd))

# ---------- 모델들 ----------
def predict_dlinear(series):
    # 간단형 DLinear: Conv1D 없이 선형 trend 분해 버전 (데모)
    x = torch.tensor(series[-CTX:], dtype=torch.float32).unsqueeze(0).unsqueeze(-1) # [1,CTX,1]
    lin = nn.Linear(CTX, HORIZ, bias=True)
    with torch.no_grad():
        y = lin.weight.sum().item() # dummy init 방지
    # 아주 단순: 마지막 값 반복(naive) + 학습 없이 형태만 맞춤
    pred = np.array([series[-1]]*HORIZ, dtype=float)
    return pred

def predict_arima(series):
    from statsmodels.tsa.arima.model import ARIMA
    endog = series[-CTX:]
    # 기본 파라미터(시작점): (p,d,q) = (5,1,0) 정도
    model = ARIMA(endog, order=(5,1,0))
    fit = model.fit()
    fc = fit.forecast(steps=HORIZ)
    return np.asarray(fc, dtype=float)

def predict_lstm(series, epochs=200, lr=1e-3):
    # 아주 작은 LSTM 예시 (1-step ahead를 반복)
    device = torch.device("cpu")
    seq = torch.tensor(series[-CTX:], dtype=torch.float32).view(1,CTX,1) # [1,T,1]
    target = torch.tensor(series[-HORIZ:], dtype=torch.float32).view(1,HORIZ,1) if HORIZ<=CTX else torch.tensor(series[-1:],dtype=torch.float32).view(1,1,1)

    class TinyLSTM(nn.Module):
        def __init__(self, hidden=32):
            super().__init__()
            self.lstm = nn.LSTM(1, hidden, batch_first=True)
            self.fc   = nn.Linear(hidden, 1)
        def forward(self, x):
            out,_ = self.lstm(x)
            return self.fc(out[:,-1:,:])  # 마지막 타임스텝 1-step

    net = TinyLSTM().to(device)
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    xtrain = seq.repeat(16,1,1)         # 미니배치 없이 증폭
    ytrain = target.repeat(16,1,1)

    for ep in range(epochs):
        net.train()
        opt.zero_grad()
        yhat = net(xtrain)
        loss = loss_fn(yhat, ytrain[:,:1,:])
        loss.backward(); opt.step()
        if (ep+1)%20==0:
            print(f"[lstm] epoch={ep+1:03d} loss={loss.item():.6f}")

    # HORIZ만큼 반복 예측 (teacher forcing 없이 naive rollout)
    preds=[]
    cur = seq.clone()
    net.eval()
    for _ in range(HORIZ):
        with torch.no_grad():
            y1 = net(cur).squeeze().item()
        preds.append(y1)
        # 다음 입력 시퀀스에 y1을 이어붙여 롤링
        nxt = torch.tensor([[y1]], dtype=torch.float32).view(1,1,1)
        cur = torch.cat([cur[:,1:,:], nxt], dim=1)
    return np.array(preds, dtype=float)

# ---------- main ----------
def main():
    df = load_series()
    series = df["price"].values.astype(float)
    last_true = df["price"].iloc[-1]
    pred_dates = pd.date_range(df["kst_date"].iloc[-1] + pd.Timedelta(days=1), periods=HORIZ, freq="D")

    if MODEL=="dlinear":
        y_pred = predict_dlinear(series)
    elif MODEL=="arima":
        y_pred = predict_arima(series)
    elif MODEL=="lstm":
        epochs = int(float(os.getenv("EPOCHS","200")))
        lr = float(os.getenv("LR","1e-3"))
        y_pred = predict_lstm(series, epochs=epochs, lr=lr)
    else:
        raise ValueError(f"unknown MODEL: {MODEL}")

    upsert_forecast(pred_dates, y_pred, last_true)
    save_minio_csv(pred_dates, y_pred)
    print(f"[done] {MODEL} saved {len(y_pred)} preds for {PAIR}")

if __name__=="__main__":
    main()
