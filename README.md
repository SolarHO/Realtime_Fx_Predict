# 📈 Realtime FX Predict
실시간 환율 수집 → 예측 모델 운영 → Superset 시각화까지 자동화한 End-to-End 파이프라인

이 프로젝트는 실시간 환율 데이터를 수집하여 PostgreSQL에 저장하고,<br>
매일 자동으로 USD/KRW 미래 환율(1일/5일/7일) 을 다양한 모델(DLinear, LSTM, GRU, ARIMA)로 예측하며,<br>
MinIO에 결과를 저장하고 Superset에서 시각화하는 완전한 MLOps 파이프라인입니다.

> **본 프로젝트는**
> **[FX_predict](https://github.com/SolarHO/FX_predict)에서 수행한**
> **USD/KRW 시계열 분석과 LSTM·GRU·DLinear 모델 비교 실험을 기반으로,**
> **데이터 수집부터 예측·저장·시각화까지 자동화한 운영형 프로젝트입니다.**

---

## ☁️ AWS 인프라 구성 (사용한 AWS 기술)

<img width="281" height="179" alt="image" src="https://github.com/user-attachments/assets/f65dbf18-ce45-4237-8c2e-b0d3bf15467b" />

이 프로젝트는 **AWS EC2** 위에 도커 스택을 올려서,  
인프라부터 수집·예측·시각화까지 모두 한 서버에서 돌아가도록 설계했습니다.

### ✅ 1. EC2 (Compute)

- **역할**: 모든 컨테이너가 올라가는 메인 서버
  - PostgreSQL, MinIO, Superset, Ingestor, Forecast 컨테이너 모두 EC2 위에서 동작
- **OS**: Ubuntu 22.04 / Amazon Linux 2023 (학습 목적/비용 절감을 위해 단일 인스턴스 사용)
- **접속**
  - SSH(22/tcp)로 접속해서 `docker-compose`, `cron`, Git 관리 등을 수행
  - `ssm-user` 계정을 사용해 개발 및 운영

### 💾 2. EBS (스토리지)

- EC2에 연결된 **EBS GP3 (약 30GB)** 에 다음 데이터가 저장됨:
  - Docker 이미지 & 컨테이너 레이어
  - PostgreSQL 데이터 (`fxdb` – 환율 시계열 + 예측 결과 테이블)
  - MinIO 데이터 디렉터리 (S3 호환 스토리지 데이터)
  - 로그 디렉터리 (`~/fx-stack/logs`) 및 각종 스크립트
- EC2를 재부팅해도 데이터가 유지되도록 **영구 스토리지 역할**을 수행

### 🔐 3. Security Group (네트워크 보안)

EC2 인스턴스에 다음과 같은 **보안 그룹 인바운드 규칙**을 설정:

| Port | 프로토콜 | 용도                             |
|------|----------|----------------------------------|
| 22   | TCP      | SSH 접속 (개발/운영용)          |
| 8088 | TCP      | Superset Web UI 접속            |
| 9000 | TCP      | MinIO 콘솔 접속                 |
| 5432 | TCP      | PostgreSQL (필요 시만 허용)     |

> 실서비스에서는 DB 포트(5432)는 내부 VPC 혹은 bastion host에서만 접근하도록 제한하는 것을 고려

### 🗄️ 4. S3 대신 MinIO 사용 (S3 호환 객체 스토리지)

- AWS S3를 직접 쓰는 대신, **EC2 내부에 MinIO 컨테이너를 올려서 S3 호환 스토리지로 사용**:
  - 엔드포인트: `http://minio:9000`
  - 버킷 이름: `fx-raw`
- 예측 결과 CSV는 다음과 같은 키 구조로 저장됨:
  - `s3://fx-raw/YYYY/MM/DD/forecast_{PAIR}_{MODEL}.csv`
  - 예: `s3://fx-raw/2025/12/05/forecast_USDKRW_gruh7.csv`
- 추후 **실제 AWS S3로 이동 시시 코드 수정 최소화**:
  - MinIO → S3로 엔드포인트/크레덴셜만 바꿔도 동일한 방식으로 동작

### ⏱ 5. Cron + systemd 기반 스케줄링

- AWS의 EventBridge 대신, **EC2 내부 `cron` 서비스**를 사용해 예측 파이프라인을 매일 스케줄링:
  - `/etc/cron.d/fx_forecast` 파일로 작업 등록
  - 매일 **09:07 KST**에 `forecast_all_horizons.sh` 실행
- 예:
  ```bash
  # 매일 09:07 KST 예측 실행
  7 9 * * * ssm-user /home/ssm-user/fx-stack/bin/forecast_all_horizons.sh >> /home/ssm-user/fx-stack/logs/forecast_cron.log 2>&1
  ```

### 📊 6. Superset + EC2 조합
- Superset 컨테이너는 EC2 상에서 동작:
  - 데이터 소스: EC2 내부의 PostgreSQL(fxdb)
  - 시각화: fx_forecast_* 뷰를 이용해 실시간/예측 데이터를 Line chart로 표현
- EC2 보안그룹에서 8088 포트를 열어 로컬 브라우저에서 http://<EC2 공인 IP>:8088 로 접속해 대시보드를 확인

---

## 🐳 Docker 기반 아키텍처
<img width="247" height="204" alt="image" src="https://github.com/user-attachments/assets/3a847fe9-ced5-4462-9c9f-879764252186" />

이 프로젝트는 **EC2 한 대** 위에서 `docker-compose` 로 모든 컴포넌트를 올리는 구조입니다.  
각 서비스는 동일한 Docker 네트워크(`fx-stack_fxnet`)를 공유하고, 컨테이너 이름으로 서로를 찾습니다.

### 🔧 주요 컨테이너 구성

| 서비스        | 컨테이너 (예시)       | 역할                                                    |
|--------------|------------------------|---------------------------------------------------------|
| PostgreSQL   | `postgres`             | 환율 시계열(`fx_rates_daily`) + 예측 결과(`fx_forecast_*`) 저장 |
| MinIO        | `minio`                | 예측 결과 CSV를 저장하는 S3 호환 스토리지 (`fx-raw` 버킷)      |
| Superset     | `superset`             | 대시보드/차트 시각화 Web UI                             |
| Ingestor     | `ingestor`             | 외부 환율 API 호출 → Kafka/DB로 실시간 환율 적재       |
| Forecast     | `forecast:any`         | DLinear/LSTM/GRU/ARIMA 등 예측 스크립트 실행            |
| (Kafka)      | `kafka`, `zookeeper`   | 실시간 스트리밍 파이프라인의 메시지 브로커             |

> 실제 컨테이너 이름과 서비스명은 `docker-compose.yml` 기준이며,  
> 모든 컨테이너는 `fx-stack_fxnet` 네트워크에서 서로를 `postgres`, `minio`, `kafka` 같은 이름으로 접근합니다.

### 📂 Docker 볼륨 & 데이터 유지

- **PostgreSQL 데이터**
  - `postgres` 컨테이너의 `/var/lib/postgresql/data` → 호스트(EBS) 볼륨에 마운트
- **MinIO 데이터**
  - `minio` 컨테이너의 `/data` → 호스트 볼륨
- **Superset 설정/메타데이터**
  - `superset_home` 디렉터리를 호스트에 마운트
- **로그 및 임시 파일**
  - `~/fx-stack/logs/` : 예측 스크립트/크론 로그
  - `~/fx-stack/tmp/`  : CSV, 중간 산출물 등 (필요 시 .gitignore 처리)

---

## 📡 Kafka 스트리밍 파이프라인 구조
<img width="318" height="159" alt="image" src="https://github.com/user-attachments/assets/bda1cb6a-a2d2-4c76-b587-028e61113334" />

### 🧩 Kafka 구성 요소

- **Kafka Broker (예: `kafka` 컨테이너)**
  - 메시지를 저장/전달하는 중앙 브로커
- **Zookeeper (예: `zookeeper` 컨테이너)**
  - 단일 브로커 환경에서 Kafka 메타데이터 관리
- **공유 네트워크**
  - 모든 컨테이너가 `fx-stack_fxnet` 네트워크에서 `kafka:9092` 로 접속

### 🧵 토픽 설계 (예시)

| 토픽 이름           | 역할                                           |
|---------------------|------------------------------------------------|
| `fx_tick_raw`       | 외부 API에서 가져온 **원본 환율 데이터**         |
| `fx_tick_clean`     | 파싱/필터링/시간대 정리 등을 거친 **정제 데이터** |
| `fx_rates_agg`      | 1분/5분/일 단위로 집계된 **종가/OHLC 데이터**     |

> 나중에 확장 시,  
> - 다른 통화쌍 (JPYKRW, EURKRW…)  
> - 다른 주기(예: 1분봉, 5분봉)  
> 에 대해서도 토픽을 추가하거나 파티션을 늘리는 식으로 확장 가능.

### 🔁 데이터 흐름 (Producer → Kafka → Consumer → DB)

전체 흐름은 대략 다음 순서로 흘러갑니다:

1. **[Ingestor 컨테이너] – Producer**
   - 외부 환율 API 호출 (예: USD/KRW 현물가)
   - 응답 JSON을 파싱하여 `fx_tick_raw` 토픽에 push
   - 필요 시 정제 후 `fx_tick_clean` 토픽으로 전달

2. **[Aggregator/Consumer] – Kafka Consumer**
   - `fx_tick_clean` 또는 `fx_tick_raw`에서 메시지 소비
   - 동일 통화쌍/시간 구간을 기준으로 집계
     - 예: 1분 또는 1일 단위 `close`/`avg` 계산
   - 결과를 PostgreSQL의 **`fx_rates_daily` / `fx_rates`** 테이블에 적재

3. **[Forecast 컨테이너] – 배치 예측**
   - 매일 09:07 KST, `forecast_all_horizons.sh`가 실행
   - `fx_rates_daily`에서 최근 N일(예: 96일) 데이터를 읽어와 학습/추론
   - 예측 결과를 다음 위치에 저장:
     - **PostgreSQL**
       - `fx_forecast_daily` (1일치)
       - `fx_forecast_h5` (5일치)
       - `fx_forecast_h7` (7일치)
     - **MinIO (S3 호환)**
       - `s3://fx-raw/YYYY/MM/DD/forecast_{PAIR}_{MODEL}.csv`

4. **[Superset 컨테이너] – BI & 대시보드**
   - 데이터 소스: PostgreSQL (`fx_forecast_*`, `fx_rates_daily`, 각종 VIEW)
   - 뷰 예:
     - `fx_forecast_daily_with_spot`
     - `fx_forecast_h5_latest_pivot`
     - `fx_forecast_h7_latest_pivot`
   - 대시보드에서:
     - 실제 환율(spot) + 1일치 예측 라인
     - 최신 5/7일치 예측 라인
     - 모델별 비교 차트 등을 시각화

### 📊 전체 플로우 다이어그램

```text
[외부 환율 API]
       │
       ▼
[Ingestor 컨테이너] --(Producer)--> [ Kafka: fx_tick_raw / fx_tick_clean ]
                                          │
                                          ▼
                             [Aggregator Consumer]
                                          │
                                          ▼
                          [PostgreSQL: fx_rates / fx_rates_daily]
                                          │
                                          ▼
        ┌─────────────────────────────────────────────────────────┐
        │             배치 예측 (매일 09:07 KST)                 │
        │ [forecast_all_horizons.sh + train_any.py/train_dlinear.py] │
        └─────────────────────────────────────────────────────────┘
                                          │
                   ┌──────────────────────┴────────────────────┐
                   ▼                                           ▼
      [PostgreSQL: fx_forecast_daily/h5/h7]        [MinIO (S3): forecast_*.csv]
                   │                                           │
                   └──────────────────────┬────────────────────┘
                                          ▼
                                 [Superset Dashboard]
```

---

## 🧠 사용 모델 & 코드 구조

이 프로젝트에서 사용하는 예측 모델들은 모두 **고정 길이 시계열 윈도우(CTX일)** 를 입력으로 받습니다.<br>  
공통 아이디어는 다음과 같습니다.

- 입력: 최근 CTX일(예: 96일) 동안의 USD/KRW 종가 시계열
- 출력:
  - H=1 → 다음 날 환율 1개 (1-step forecast)
  - H=5 → 앞으로 5일치 환율 벡터
  - H=7 → 앞으로 7일치 환율 벡터
- 공통 전처리:
  - `fx_rates_daily` 에서 PAIR(예: USDKRW)에 해당하는 시계열 로드
  - 학습 구간 평균/표준편차로 **표준화(z-score)** 후 모델 입력
  - 예측 후 다시 **원래 스케일로 역변환**

모델 학습과 추론은 크게 두 가지 스크립트로 나뉩니다.

- `forecast_image_src/app/train_dlinear.py` : DLinear 전용 학습 + 예측 + 저장
- `forecast_image_src/app/train_any.py`     : ARIMA / LSTM / GRU 등 공통 인터페이스

---

### 📦 1. 공통 데이터 파이프라인 (`train_any.py` / `train_dlinear.py`)

모든 모델이 공통으로 사용하는 데이터 로딩/전처리 흐름은 다음과 같습니다.

1. **PostgreSQL에서 시계열 로드**
   ```python
   def load_series(pair: str) -> pd.Series:
       # fx_rates_daily 또는 유사 뷰에서 특정 pair 시계열 로드
       # 인덱스: kst_date, 값: price

2. **윈도우 생성**
  - 길이 CTX(96일)짜리 슬라이딩 윈도우를 생성
  - 입력 X: [N, CTX], 타겟 y: [N] 또는 [N, H]

3. 학습/검증 분리
  - 시계열 기준 80:20 비율로 **과거/최근** 구간을 train/val 로 나눔

4. 표준화
  - 학습 구간 기준 mu, sigma를 구해서:
    - X_norm = (X - mu) / sigma
    - 추론 결과는 y_pred = y_norm * sigma + mu 로 역변환

5. 결과 저장
  - save_pg(...) : fx_forecast_daily, fx_forecast_h5, fx_forecast_h7 에 UPSERT
  - upload_minio(...) : forecast_{PAIR}_{MODEL}.csv 로 MinIO(S3) 업로드

### 🟦 2. DLinear 모델 (train_dlinear.py)
DLinear는 복잡한 RNN 대신, 순수한 선형 레이어만 사용하는 경량 시계열 모델입니다.
```
class DLinear(nn.Module):
    def __init__(self, ctx, horizon):
        super().__init__()
        self.fc = nn.Linear(ctx, horizon)  # CTX → H일치 예측

    def forward(self, x):
        # x: [B, CTX, 1]
        x = x.squeeze(-1)                  # [B, CTX]
        out = self.fc(x)                   # [B, H]
        return out
```

### 🟩 3. LSTM 모델 (train_any.py 내 LSTM 계열)
LSTM은 장기 의존성(Long-term dependency) 를 학습할 수 있는 RNN 계열 모델입니다.
```
class FxLSTM(nn.Module):
    def __init__(self, ctx, hidden_size=64, num_layers=2, horizon=1):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=1,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.fc = nn.Linear(hidden_size, horizon)

    def forward(self, x):
        # x: [B, CTX, 1]
        out, (h_n, c_n) = self.lstm(x)      # out: [B, CTX, H], h_n: [L, B, H]
        last_h = h_n[-1]                    # [B, H] - 마지막 레이어의 최종 hidden state
        y = self.fc(last_h)                 # [B, horizon]
        return y
```

### 🟥 4. GRU 모델 (train_any.py 내 GRU 계열)
GRU는 LSTM보다 구조가 단순한 RNN으로, 파라미터 수가 적고 학습 속도가 빠른 장점이 있습니다.
```
class FxGRU(nn.Module):
    def __init__(self, ctx, hidden_size=64, num_layers=2, horizon=1):
        super().__init__()
        self.gru = nn.GRU(
            input_size=1,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.fc = nn.Linear(hidden_size, horizon)

    def forward(self, x):
        out, h_n = self.gru(x)        # h_n: [L, B, H]
        last_h = h_n[-1]              # [B, H]
        y = self.fc(last_h)           # [B, H]
        return y
```

### 📘 5. ARIMA 모델 (train_any.py 내 ARIMA)
ARIMA는 전통적인 통계 시계열 모델로, 추세/자기상관을 선형 모형으로 설명합니다.
```
from statsmodels.tsa.arima.model import ARIMA

def predict_arima(series, h):
    model = ARIMA(series.values, order=(1, 1, 1))
    fit = model.fit()
    fc = fit.forecast(steps=h)
    return np.asarray(fc, dtype=float)
```

### 🔁 6. Horizon(1/5/7일) 처리 방식
모든 모델은 공통으로 H 파라미터를 통해 예측 길이를 제어합니다.
- H=1 : 다음 날 1개 값만 예측 → fx_forecast_daily
- H=5 : 5일치 벡터 예측 → fx_forecast_h5
- H=7 : 7일치 벡터 예측 → fx_forecast_h7

학습 시에는:
- 입력: [B, CTX, 1]
- 타겟: [B, H] (예: 5일치/7일치 구간)
- 마지막 윈도우 기준으로 **미래 H일을 한 번에 예측**하는 구조

### 🧾 7. 예측 결과 저장 로직 (공통)
train_any.py / train_dlinear.py 에서 사용하는 save_pg(...) 함수는<br>
H 값에 따라 자동으로 테이블을 분기하고, (kst_date, pair, model) 기준으로 UPSERT 합니다.
```
def save_pg(pred_dates, y_pred, last_true, model_label):
    horizon = int(os.getenv("H", "1"))
    if horizon == 1:
        table_name = "fx_forecast_daily"
    elif horizon == 5:
        table_name = "fx_forecast_h5"
    elif horizon == 7:
        table_name = "fx_forecast_h7"
    else:
        table_name = "fx_forecast_long"

    # (kst_date, pair, model) 기준 ON CONFLICT DO UPDATE
    # y_pred, y_true, run_ts 갱신
```


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

**4️⃣ 전체 대시보드 요약**

Superset 대시보드 화면<br>
실제 환율 데이터 + 각 모델의 하루, 5일, 7일치 예측 그래프
<img width="1900" height="940" alt="image" src="https://github.com/user-attachments/assets/5269067d-5b42-4f6c-9d8f-8c3e2e07a4c2" />

## 모델 성능 분석 결론(대시보드 기반)

### 1. DLinear 모델 — 전체 Horizon(1일/5일/7일)에서 가장 안정적인 성능
- 실제 환율 추세(Spot) 과 가장 비슷한 수준에서 움직이며 과도한 상승/하락 없이 완만하고 현실적인 예측 패턴을 보임
- 특히 5일치·7일치 예측에서도 예측값의 폭이 안정적이고 실제 환율 레벨을 크게 벗어나지 않음
**👉 실제 시장 움직임을 가장 잘 반영하는 모델로 판단됨**

### 2. ARIMA — 단기 예측(1일치)에서는 강하지만, 중기 예측(5·7일)에서는 방향성이 단순
- 1일 예측에서는 Spot(실제 환율 변동)과 유사한 패턴
- 5일·7일 Forecast에서는 수평선처럼 거의 변화가 없는 패턴을 보여줌
**👉 단기(1일)에만 적합하고 중기 예측에서는 정보량이 떨어짐**

### 3. LSTM — 비교적 안정적이며 Spot과 유사한 흐름을 유지
- 1일·7일 예측 그래프에서 Spot 대비 큰 이탈 없이 점진적인 상승/하락 패턴을 학습한 모습을 보임
- DLinear보다는 오차 폭이 조금 더 넓음
**👉 LSTM은 안정적이지만 DLinear만큼 시장 수준을 잘 따라가지 못함**

### 4. GRU — 5·7일 예측에서 가장 과한 하락 예측
- 5일·7일 Forecast 모두에서 지속적인 강한 하락을 예측, 실제 Spot보다 훨씬 낮은 값으로 예측됨
- 최근 데이터의 일부 패턴을 과하게 반영(Overfitting)했거나 장기 Horizon에서 추세 왜곡이 발생한 것이 의심됨
**👉 장기 예측에서 신뢰도가 가장 낮음**

### 🎯 최종 결론
| 모델          | 단기 (1일)     | 중기 (5·7일)    | 종합 평가                  |
| ----------- | ----------- | ------------ | ---------------------- |
| **DLinear** | 👍 매우 좋음    | 👍 안정적       | **전체적으로 가장 뛰어난 예측 성능** |
| **LSTM**    | 👍 좋음       | 👍 무난함       | 안정적이지만 약간의 편향 존재       |
| **ARIMA**   | 👍 단기 매우 좋음 | ⚠️ 중기 한계     | 단기 전용 모델에 가깝다          |
| **GRU**     | 😐 보통       | ❌ 비현실적 하락 예측 | 장기 예측에는 부적합            |
