FROM fxstack/forecast:any

# 원래 컨테이너도 /app 을 워킹 디렉터리로 쓰고 있었으니까 동일하게 맞춰줌
WORKDIR /app

# 현재 디렉토리(패치된 소스)를 컨테이너 /app 에 통째로 복사
COPY . /app
