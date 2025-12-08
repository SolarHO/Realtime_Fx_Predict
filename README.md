# 📈 Realtime FX Predict
실시간 환율 수집 → 예측 모델 운영 → Superset 시각화까지 자동화한 End-to-End 파이프라인

이 프로젝트는 실시간 환율 데이터를 수집하여 PostgreSQL에 저장하고,<br>
매일 자동으로 USD/KRW 미래 환율(1일/5일/7일) 을 다양한 모델(DLinear, LSTM, GRU, ARIMA)로 예측하며,<br>
MinIO에 결과를 저장하고 Superset에서 시각화하는 완전한 MLOps 파이프라인입니다.

---

## 🏗️ 전체 아키텍처

---

## 1️⃣ EC2 인스턴스 생성

**✔ 인스턴스 사양**
- Ubuntu 22.04 / Amazon Linux 2023
- vCPU 2 ~ 4
- RAM 4GB
- Storage: 30GB GP3
- Security Group:
  - 22/tcp (SSH)
  - 8088/tcp (Superset)
  - 9000/tcp (MinIO 콘솔)
  - 5432/tcp (PostgreSQL)
 
---

## 2️⃣ 기본 개발 환경 설치(docker)

```
sudo apt update && sudo apt upgrade -y
sudo apt install docker.io docker-compose git -y
sudo usermod -aG docker $USER
```

---

## 3️⃣ Repository 클론
```
git clone https://github.com/SolarHO/Realtime_Fx_Predict.git
cd Realtime_Fx_Predict
```

---

## 4️⃣ .env 설정
```
POSTGRES_USER=fxuser
POSTGRES_PASSWORD=fxpass123
POSTGRES_DB=fxdb

MINIO_ROOT_USER=fxminio
MINIO_ROOT_PASSWORD=fxpass123
MINIO_BUCKET=fx-raw
```

---

## 5️⃣ Docker Compose 실행
```
docker-compose up -d
```
준비되는 서비스:
| 서비스        | 설명                |
| ---------- | ----------------- |
| PostgreSQL | 환율 & 예측 결과 저장     |
| MinIO      | 예측 CSV 저장용 S3     |
| Superset   | Dashboard 시각화     |
| Ingestor   | 실시간 환율 수집         |
| Forecast   | ML 모델들이 돌아가는 컨테이너 |

---

## 6️⃣ 데이터 수집 파이프라인 (Ingestor)
**✔ 기능**
- 1분 또는 5분 단위로 실시간 환율 API 호출
- PostgreSQL의 fx_rates 테이블에 저장
<br>fx_rates 스키마:
| 컬럼    | 설명         |
| ----- | ---------- |
| ts    | 타임스탬프(KST) |
| pair  | 통화쌍        |
| price | 실제 환율      |

---

## 7️⃣ 예측 모델(ML) 학습/추론 파이프라인
Forecast 컨테이너는 여러 모델을 실행할 수 있도록 통합된 구조:

**지원 모델**
- DLinear
- LSTM
- GRU
- ARIMA

**예측 Horizon**
- 1일치
- 5일치
- 7일치

**실행 스크립트**
```
~/fx-stack/bin/forecast_all_horizons.sh
```
- 매일 09:07 자동 실행 (KST)
- 각 모델 & horizon 조합을 모두 수행
- 결과를 PostgreSQL & MinIO 에 저장
ex)
| 테이블               | 설명     |
| ----------------- | ------ |
| fx_forecast_daily | 1일치 예측 |
| fx_forecast_h5    | 5일치 예측 |
| fx_forecast_h7    | 7일치 예측 |

---

## 8️⃣ MinIO S3 저장
예측 CSV 예시:
```
s3://fx-raw/2025/12/05/forecast_USDKRW_gruh7.csv
```

---

## 9️⃣ Superset 대시보드 구성

**주요 차트들**

**(1) 실제 환율 + 1일 예측 누적 라인**<br>
Data source: fx_forecast_daily_with_spot

**(2) 5일치 최신 예측 라인**<br>
Data source: fx_forecast_h5_latest_pivot

**(3) 7일치 최신 예측 라인**<br>
Data source: fx_forecast_h7_latest_pivot

**(4) 모델별 1일 예측 성능 비교**<br>
MAE / MAPE 그래프 등 확장 가능

---

## 🔟 SQL 뷰 구성

**Spot + 1일 예측 결합 뷰**
```
CREATE VIEW fx_forecast_daily_with_spot AS
SELECT
    f.kst_date,
    f.pair,
    f.model,
    f.y_pred,
    r.spot
FROM fx_forecast_daily AS f
LEFT JOIN fx_rates_daily AS r
ON r.kst_date = f.kst_date AND r.pair = f.pair;
```
**5·7일치 예측 최신 실행 기준 Pivot View**
- fx_forecast_h5_latest_pivot
- fx_forecast_h7_latest_pivot

---

## 1️⃣1️⃣ Cron 자동화

EC2 사용자 ssm-user 기준:
```
sudo tee /etc/cron.d/fx_forecast <<EOF
# 매일 09:07 KST 예측 실행
7 9 * * * ssm-user /home/ssm-user/fx-stack/bin/forecast_all_horizons.sh >> /home/ssm-user/fx-stack/logs/forecast_cron.log 2>&1
EOF

sudo systemctl restart cron
```

---

## 1️⃣2️⃣ 프로젝트 파일 구조
```
fx-stack/
├── docker-compose.yml
├── .env
├── bin/
│   └── forecast_all_horizons.sh
├── forecast_image_src/
│   └── app/
│       ├── train_any.py
│       ├── train_dlinear.py
├── sql/
│   ├── views_daily.sql
│   ├── views_h5.sql
│   ├── views_h7.sql
├── logs/
└── tmp/
```

---

## 1️⃣3️⃣ 사용 예시

**예측 모델 수동 실행**
```
docker run --rm --network fx-stack_fxnet \
  -e MODEL="dlinear" -e PAIR="USDKRW" -e H="7" \
  fxstack/forecast:any train_any.py
```

---

# 📈 Dashboard Overview

**1️⃣ 실시간 환율 + 1일치 예측 비교 (Daily Forecast + Spot)**

모든 모델(DLinear, GRU, LSTM, ARIMA)의 1일치 예측과 실제 환율 라인을 한눈에 비교할 수 있는 메인 차트
<img width="913" height="495" alt="image" src="https://github.com/user-attachments/assets/b45321d3-4956-4d4e-9cc4-a1784fbfdcfc" />

**2️⃣ 최신 5일치 예측 그래프 (Latest H5 Forecast)**

각 모델이 가장 최근 실행(run_ts 기준)에서 생성한 5일치 예측 데이터를 보여줍니다.
<img width="607" height="358" alt="image" src="https://github.com/user-attachments/assets/159dbf24-ba9f-4389-97d0-5cd6ee86ad55" />

**3️⃣ 최신 7일치 예측 그래프 (Latest H7 Forecast)**

각 모델이 가장 최근 실행(run_ts 기준)에서 생성한 7일치 예측 데이터를 보여줍니다.
<img width="602" height="356" alt="image" src="https://github.com/user-attachments/assets/18966f0b-0b50-4e98-af4d-497b97569af2" />
