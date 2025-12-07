import re, pathlib
p = pathlib.Path('train_any.py')
s = p.read_text(encoding='utf-8')

# def save_pg( ... ):
pat = re.compile(r'(^def\s+save_pg\([^\)]*\):\s*\n)', re.M)

# 이미 우리가 넣었던 줄이 있으면 중복 삽입 안 함
inject = '    table_name = locals().get("table_name") or target_table(MODEL, H)\n'

def repl(m):
    head = m.group(1)
    return head + inject

if inject not in s:
    s_new, n = pat.subn(repl, s, count=1)
    if n == 0:
        raise SystemExit("save_pg() 함수를 찾지 못했습니다.")
    p.write_text(s_new, encoding='utf-8')
    print("patched: inserted table_name line into save_pg()")
else:
    print("skip: already patched")
