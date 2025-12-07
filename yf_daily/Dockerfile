FROM python:3.11-slim

# 필수 도구 설치(curl) -> supercronic 바이너리 다운로드
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL -o /usr/local/bin/supercronic \
      https://github.com/aptible/supercronic/releases/download/v0.2.30/supercronic-linux-amd64 \
 && chmod +x /usr/local/bin/supercronic

# 작업 디렉터리
WORKDIR /app

# Python 패키지(캐시 최대 활용)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 앱 복사
COPY app.py /app/app.py

# 크론 파일 복사
COPY cron/yf.cron /etc/cron.d/yf.cron

# 환경변수 (필요시 compose에서 override)
ENV LOCAL_TZ=Asia/Seoul \
    PAIRS=USDKRW \
    RUN_AT=09:05 \
    SAVE_TO_MINIO=true

# supercronic 실행
ENTRYPOINT ["supercronic", "-quiet", "/etc/cron.d/yf.cron"]
