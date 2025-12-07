import re, pathlib
p = pathlib.Path('train_any.py')
s = p.read_text(encoding='utf-8')

# save_pg 함수 전체를 찾아 다음 구현으로 교체
pattern = re.compile(r'^def\s+save_pg\([^\)]*\):[\s\S]*?(?=^def\s+|\Z)', re.M)

replacement = '''
def save_pg(pred_dates, y_pred, last_true, model_label):
    """
    pred_dates: 예측된 날짜 배열(list[datetime/date])
    y_pred    : 예측값 배열(list/ndarray[float])
    last_true : 가장 최근 실측가(float|None)
    model_label: 저장할 모델 라벨(문자열, ex. 'dlinearh5')
    """
    import math
    from sqlalchemy import MetaData, Table, Column, Date, String, Float
    from sqlalchemy.dialects.postgresql import insert

    # 대상 테이블 자동 선택 (daily/h5/h7)
    table_name = target_table(model_label, H)

    eng = get_engine()
    rows = []
    for d, y in zip(pred_dates, y_pred):
        rows.append({
            "kst_date": d.date() if hasattr(d, "date") else d,
            "pair": PAIR,
            "model": model_label,  # 라벨 그대로 저장
            "y_true": float(last_true) if last_true is not None and not (isinstance(last_true, float) and math.isnan(last_true)) else None,
            "y_pred": float(y) if y is not None and not (isinstance(y, float) and math.isnan(y)) else None,
            "yhat_lo": None,
            "yhat_hi": None,
        })

    meta = MetaData()
    tbl = Table(table_name, meta,
        Column('kst_date', Date, primary_key=True),
        Column('pair',     String, primary_key=True),
        Column('model',    String, primary_key=True),
        Column('y_true',   Float),
        Column('y_pred',   Float),
        Column('yhat_lo',  Float),
        Column('yhat_hi',  Float),
    )

    stmt = insert(tbl)
    upsert = stmt.on_conflict_do_update(
        index_elements=['kst_date','pair','model'],
        set_={
            'y_true' : stmt.excluded.y_true,
            'y_pred' : stmt.excluded.y_pred,
            'yhat_lo': stmt.excluded.yhat_lo,
            'yhat_hi': stmt.excluded.yhat_hi,
        }
    )

    with eng.begin() as conn:
        conn.execute(upsert.values(rows))
'''

s2, n = pattern.subn(replacement.strip() + '\n', s, count=1)
if n == 0:
    raise SystemExit("save_pg() 함수를 찾지 못했습니다. 파일 구조를 확인하세요.")
p.write_text(s2, encoding='utf-8')
print("patched save_pg()")
