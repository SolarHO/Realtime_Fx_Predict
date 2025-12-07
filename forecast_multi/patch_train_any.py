import re, pathlib

p = pathlib.Path('train_any.py')
s = p.read_text(encoding='utf-8')

# 1) save_pg 시그니처: save_pg(table_name, pred_dates, y_pred, last_true)
s, n1 = re.subn(
    r'def\s+save_pg\(\s*pred_dates\s*,\s*y_pred\s*,\s*last_true\s*\)\s*:',
    'def save_pg(table_name, pred_dates, y_pred, last_true):',
    s
)

# 2) save_pg 내부 테이블명 하드코딩 -> 변수 table_name
s, n2 = re.subn(
    r"Table\('fx_forecast_[a-z0-9_]+'\s*,",
    "Table(table_name,",
    s
)

# 3) 모델/H에 따라 저장 대상 테이블 고르기
if 'def target_table(' not in s:
    s = s.replace(
        'def upload_minio',
        '''def target_table(model: str, H: int) -> str:
    m = (model or "").lower()
    if m.endswith("h5") or H == 5:
        return "fx_forecast_h5"
    if m.endswith("h7") or H == 7:
        return "fx_forecast_h7"
    return "fx_forecast_daily"

def upload_minio'''
    )

# 4) main()에서 save_pg 호출부에 table_name 전달
s, n4 = re.subn(
    r'(#\s*저장\s*\n)\s*save_pg\(\s*pred_dates\s*,\s*y_pred\s*,\s*last_true\s*\)',
    r'\1    tbl = target_table(MODEL, H)\n    save_pg(tbl, pred_dates, y_pred, last_true)',
    s
)

# 5) (안전망) MinIO 파일명이 모델 반영되도록 통일
s = re.sub(r"forecast_\{PAIR\}_dlinear\.csv", "forecast_{PAIR}_{MODEL}.csv", s)
s = re.sub(r"forecast_\{PAIR\}\.csv",        "forecast_{PAIR}_{MODEL}.csv", s)

pathlib.Path('train_any.py').write_text(s, encoding='utf-8')

print("patch done:",
      {"sig_changed": n1, "table_var": n2, "main_call": n4})
