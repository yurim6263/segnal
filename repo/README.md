# 연주기 냉각수 누수 조기 감지 — 해커톤 소스코드

AI 기반 연주기 냉각수 누수 조기 감지와 점검 위치 후보 제시. (문서: 상위 폴더의 `01~05` md 파일)

> 모든 데이터는 **합성 데이터**이고 경보 기준값 등 파라미터는 **가설**입니다. 효과는 시뮬레이션 기준입니다.

## 구성
```
config/plant.yaml   세그먼트 수·계측 묶음·시뮬레이터 가정 (현업 답변이 오면 여기만 수정)
backend/            FastAPI + 시뮬레이터 + 감지·위치 후보·평가 (Python 3.12)
frontend/           React + Vite + Tailwind + Recharts 웹 대시보드
data/               생성된 합성 데이터, SQLite 파일
docs/               현업 질문 문안 등
```

## 실행
```
# 1) 백엔드 (처음 한 번)
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
# 합성 데이터 생성 (데모 시나리오는 저장소에 들어 있어 건너뛰어도 실행됩니다)
# 평가용 시나리오까지 전부 다시 만들 때: 약 140MB, 몇 분 걸립니다
.venv\Scripts\python -m sim.generate --eval-n 30 --eval-events 12 --eval-prior 30
# 평가 다시 돌리기: python -m eval.tune_detectors / classify_eval / localize_eval / inspection_eval / sensitivity_eval
# (선택) 오토인코더 비교: pip install torch (CPU)
# 서버
.venv\Scripts\python -m uvicorn main:app --reload --port 8000

# 2) 프론트엔드 (처음 한 번 npm install)
cd frontend
npm install
npm run dev      # http://localhost:5173
```
`run.bat`이 위 실행을 한 번에 합니다.

## 테스트
```
cd backend
.venv\Scripts\python -m pytest -q
```
