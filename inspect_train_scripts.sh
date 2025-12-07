#!/usr/bin/env bash
set -e

APP_DIR="${APP_DIR:-./forecast_image_src/app}"

if [ ! -d "$APP_DIR" ]; then
  echo "ERROR: $APP_DIR 디렉터리가 없습니다. 먼저 컨테이너에서 코드를 복사해야 합니다." >&2
  exit 1
fi

cd "$APP_DIR"

echo "[*] 현재 디렉터리: $(pwd)"
echo "[*] 대상 파일: train_any.py, train_dlinear.py"
echo

# 공통적으로 자주 나오는 DB/저장 관련 키워드들
KEYWORDS=(
  "fx_forecast"
  "INSERT INTO"
  "to_sql"
  "create_engine"
  "psycopg2"
  "MINIO"
  "s3://"
  "save"
  "postgres"
)

for f in train_any.py train_dlinear.py; do
  if [ ! -f "$f" ]; then
    echo "[-] $f 파일이 없습니다. 건너뜁니다."
    continue
  fi

  echo "========================================"
  echo "== 파일: $f"
  echo "========================================"

  for kw in "${KEYWORDS[@]}"; do
    echo
    echo "--- 키워드 검색: '$kw' ---"
    # -n: 줄번호, -I: 바이너리 파일 무시, -C2: 앞뒤 두 줄 context
    if ! grep -nI -C2 --color=always "$kw" "$f" 2>/dev/null; then
      echo "( '$kw' 관련 내용 없음 )"
    fi
  done

  echo
done

echo
echo "[*] 위 결과에서 'INSERT INTO', 'to_sql', 'fx_forecast_*'가 나오는 부분이"
echo "    실제 Postgres에 저장하는 지점이야."
echo "    그 부분을 수정해서 모든 모델(H=1,5,7)을 fx_forecast_* 테이블에 쓰도록 바꾸면 된다."
