#!/usr/bin/env bash
set -euo pipefail
cd ~/fx-stack

# 기존 override 백업
[[ -f docker-compose.override.yml ]] && cp -f docker-compose.override.yml docker-compose.override.yml.bak.$(date +%Y%m%d%H%M%S)

# gevent -> gthread 로 변경 + 절대경로 유지
cat > docker-compose.override.yml <<'YAML'
services:
  superset:
    environment:
      SQLALCHEMY_DATABASE_URI: postgresql+psycopg2://fxuser:fxpass123@postgres:5432/fxdb
      SUPERSET_LOAD_EXAMPLES: "no"
      SUPERSET_SECRET_KEY: 390a3d878b907f8fb6c1d9928c65b54fb971254669617529a7d22134b8bc2eae
    command: >
      /bin/bash -lc "/app/.venv/bin/superset db upgrade &&
      (/app/.venv/bin/superset fab create-admin --username admin --firstname Sunho --lastname Lee --email admin@example.com --password admin123 || true) &&
      /app/.venv/bin/superset init &&
      /app/.venv/bin/gunicorn -w 2 -k gthread --threads 8 --timeout 120 -b 0.0.0.0:8088 'superset.app:create_app()'"
YAML

echo "== merged superset block =="
docker compose -f docker-compose.yml -f docker-compose.override.yml config | sed -n '/^  superset:/,/^[^ ]/p'

echo "== recreate superset =="
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --no-deps --force-recreate superset

echo "== tail logs (Ctrl+C로 종료) =="
docker logs -f --tail=120 superset
