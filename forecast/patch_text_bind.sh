#!/usr/bin/env bash
set -euo pipefail
cd ~/fx-stack/forecast

python - <<'PY'
import re, pathlib
p = pathlib.Path('train_dlinear.py')
s = p.read_text()

# import 보강
if "from sqlalchemy import text" not in s:
    s = s.replace("from sqlalchemy import create_engine",
                  "from sqlalchemy import create_engine, text")

# read_sql()을 text(sql)로 변경 (첫 1회만)
s = re.sub(
    r"pd\.read_sql\(\s*sql\s*,\s*get_engine\(\)\s*,\s*params\s*=\s*\{[^}]*\}\s*\)",
    "pd.read_sql(text(sql), get_engine(), params={\"pair\": PAIR})",
    s, count=1
)

p.write_text(s)
print("patched:", p)
PY
