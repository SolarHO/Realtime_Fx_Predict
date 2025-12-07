import os, sys, time
from dateutil import parser as dtp
from kafka import KafkaConsumer
import psycopg2

kafka_bootstrap = os.getenv("KAFKA_BOOTSTRAP","kafka:19092")
topic = os.getenv("KAFKA_TOPIC","fx_rate_raw")
pg_dsn = f"dbname={os.getenv('POSTGRES_DB')} user={os.getenv('POSTGRES_USER')} password={os.getenv('POSTGRES_PASSWORD')} host=postgres port=5432"

def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS fx_rates (
          ts timestamptz PRIMARY KEY,
          pair text NOT NULL,
          price numeric(12,6) NOT NULL
        );""")
    conn.commit()

def main():
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=[kafka_bootstrap],
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        group_id="fx_ingestor_g1",
        value_deserializer=lambda v: v.decode("utf-8")
    )
    conn = psycopg2.connect(pg_dsn)
    ensure_table(conn)
    print(f"[ingestor] consuming from {topic} on {kafka_bootstrap}", flush=True)

    while True:
        for msg in consumer.poll(timeout_ms=1000).values():
            for record in msg:
                try:
                    pair, price, ts = [x.strip() for x in record.value.split(",")]
                    ts_parsed = dtp.parse(ts)
                    with conn.cursor() as cur:
                        cur.execute("""
                          INSERT INTO fx_rates(ts, pair, price)
                          VALUES (%s, %s, %s)
                          ON CONFLICT (ts) DO UPDATE SET pair=EXCLUDED.pair, price=EXCLUDED.price
                        """, (ts_parsed, pair, price))
                    conn.commit()
                    print(f"[OK] {record.value}", flush=True)
                except Exception as e:
                    conn.rollback()
                    print(f"[ERR] {record.value} -> {e}", file=sys.stderr, flush=True)
        time.sleep(0.2)

if __name__ == "__main__":
    main()
