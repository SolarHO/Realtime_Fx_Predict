import os, time, io, datetime as dt
import pandas as pd
import yfinance as yf
import psycopg2
from dateutil import tz
import argparse
import boto3, requests

# Yahoo 심볼 매핑: USDKRW는 KRW=X
YF_TICKER_MAP = {
    "USDKRW": "KRW=X",
}

PAIRS = [s.strip() for s in os.getenv("PAIRS","USDKRW").split(",") if s.strip()]
TZ = tz.gettz(os.getenv("LOCAL_TZ","Asia/Seoul"))
RUN_AT = os.getenv("RUN_AT","09:05")
SAVE_TO_MINIO = os.getenv("SAVE_TO_MINIO","true").lower() == "true"

PG_DSN = (
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')} "
    f"host=postgres port=5432"
)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT","http://minio:9000")
MINIO_ACCESS = os.getenv("MINIO_ROOT_USER")
MINIO_SECRET = os.getenv("MINIO_ROOT_PASSWORD")
MINIO_BUCKET = os.getenv("MINIO_BUCKET","fx-raw")

def log(*a, **k): print(*a, **k, flush=True)

def upsert_fx_rates(rows):
    conn = psycopg2.connect(PG_DSN)
    with conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS fx_rates (
          ts timestamptz NOT NULL,
          pair text NOT NULL,
          price numeric(12,6) NOT NULL
          , PRIMARY KEY (ts, pair)
        );
        """)
        for ts_utc, pair, price in rows:
            cur.execute("""
              INSERT INTO fx_rates(ts, pair, price)
              VALUES (%s, %s, %s)
              ON CONFLICT (ts, pair) DO UPDATE SET price=EXCLUDED.price
            """, (ts_utc, pair, price))
    conn.close()

def save_minio_csv(rows, run_dt_local):
    if not SAVE_TO_MINIO: return
    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
        region_name="us-east-1",
    )
    date_path = run_dt_local.strftime("%Y/%m/%d")
    df = pd.DataFrame(rows, columns=["ts_utc","pair","price"])
    key = f"{date_path}/yf_daily_{run_dt_local.strftime('%H%M%S')}.csv"
    s3.put_object(Bucket=MINIO_BUCKET, Key=key, Body=df.to_csv(index=False).encode("utf-8"))
    log(f"[minio] saved s3://{MINIO_BUCKET}/{key} ({len(rows)} rows)")

def fetch_yahoo_pair(pair, retries=3, sleep_s=2):
    tkr = YF_TICKER_MAP.get(pair, f"{pair}=X")
    last_err = None
    for _ in range(retries):
        try:
            df = yf.download(
                tickers=tkr, period="5d", interval="1d",
                progress=False, auto_adjust=False,
                group_by="column", threads=False, timeout=30
            )
            if isinstance(df.columns, pd.MultiIndex):
                close = df[tkr]["Close"]
            else:
                close = df["Close"]
            close = close.dropna()
            if not close.empty:
                return float(close.iloc[-1])
            last_err = "no close data"
        except Exception as e:
            last_err = str(e)
        time.sleep(sleep_s)
    log(f"[yahoo-fail] {pair}: {last_err}")
    return None

def fetch_stooq_pair(pair, retries=2, sleep_s=1):
    sym = pair.lower()
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    last_err = None
    for _ in range(retries):
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            if not df.empty and "Close" in df.columns:
                return float(df["Close"].iloc[-1])
            last_err = "no Close col"
        except Exception as e:
            last_err = str(e)
        time.sleep(sleep_s)
    log(f"[stooq-fail] {pair}: {last_err}")
    return None

def fetch_once(run_dt_local):
    rows = []
    base_now_utc = dt.datetime.now(dt.timezone.utc)
    for idx, pair in enumerate(PAIRS):
        price = fetch_yahoo_pair(pair)
        if price is None:
            price = fetch_stooq_pair(pair)
        if price is None:
            log(f"[warn] no data for {pair}")
            continue
        ts_utc = base_now_utc + dt.timedelta(seconds=idx)  # PK(ts) 충돌 방지
        rows.append((ts_utc, pair, price))
        log(f"[ok] {pair}={price}")
    if rows:
        upsert_fx_rates(rows)
        save_minio_csv(rows, run_dt_local)
        log(f"[done] upserted {len(rows)} rows into Postgres")
    else:
        log("[skip] nothing to upsert")

def seconds_until(target_hhmm, tzinfo):
    hh, mm = map(int, target_hhmm.split(":"))
    now = dt.datetime.now(tzinfo)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target = target + dt.timedelta(days=1)
    return int((target - now).total_seconds())

def main():
    log(f"[init] PAIRS={PAIRS} RUN_AT={RUN_AT} TZ={TZ}")
    fetch_once(dt.datetime.now(TZ))  # startup run
    while True:
        wait = seconds_until(RUN_AT, TZ)
        log(f"[sleep] waiting {wait}s until {RUN_AT} ({TZ})")
        time.sleep(wait)
        fetch_once(dt.datetime.now(TZ))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run once then exit")
    args = ap.parse_args()

    log(f"[init] PAIRS={PAIRS} RUN_AT={RUN_AT} TZ={TZ}")
    if args.once:
        # 한 번만 실행하고 종료 (supercronic 용)
        fetch_once(dt.datetime.now(TZ))
    else:
        # 기존 스케줄 루프
        fetch_once(dt.datetime.now(TZ))
        while True:
            wait = seconds_until(RUN_AT, TZ)
            log(f"[sleep] waiting {wait}s until {RUN_AT} ({TZ})")
            time.sleep(wait)
            fetch_once(dt.datetime.now(TZ))
