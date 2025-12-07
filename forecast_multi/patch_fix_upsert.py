import re, pathlib
p = pathlib.Path('train_any.py')
s = p.read_text(encoding='utf-8')

# save_pg 내부의 upsert 블록 교체: ins 자기참조 제거
pattern = re.compile(
    r"ins\s*=\s*insert\(tbl\)\.values\(rows\)\.on_conflict_do_update\([\s\S]*?^\s*with\s+eng\.begin\(\)\s+as\s+conn:\s*\n\s*conn\.execute\(ins\)",
    re.M
)

replacement = """stmt = insert(tbl)
upsert = stmt.on_conflict_do_update(
    index_elements=['kst_date','pair','model'],
    set_={
        'y_true':  stmt.excluded.y_true,
        'y_pred':  stmt.excluded.y_pred,
        'yhat_lo': stmt.excluded.yhat_lo,
        'yhat_hi': stmt.excluded.yhat_hi,
    }
)
with eng.begin() as conn:
    conn.execute(upsert.values(rows))"""

s2, n = pattern.subn(replacement, s, count=1)
if n == 0:
    # 혹시 values(rows) 없이 구성된 변형 케이스까지 커버
    pattern2 = re.compile(
        r"ins\s*=\s*insert\(tbl\)[\s\S]*?on_conflict_do_update\([\s\S]*?^\s*with\s+eng\.begin\(\)\s+as\s+conn:\s*\n\s*conn\.execute\(ins\)",
        re.M
    )
    s2, n = pattern2.subn(replacement, s, count=1)

if n == 0:
    raise SystemExit("패치할 upsert 블록을 찾지 못했습니다.")
p.write_text(s2, encoding='utf-8')
print("patched upsert block in save_pg()")
