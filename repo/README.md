# 연주기 냉각수 누수 조기 감지 — 해커톤 소스코드

AI 기반 연주기 냉각수 누수 조기 감지와 점검 위치 후보 제시. **팀 기준 문서는 `세그널_기획서_최종본.md`(누수 예측·예방 + Claude 작업지시서)이고, 이 저장소의 현재 코드는 그 기획서의 E1(조기 감지 안전망)과 재사용 부품입니다. 기획서 MVP와의 매핑은 `03_팀_구현내용.md` §A.** (문서: 상위 폴더의 `01~08` md 파일. 구현 상태와 측정 결과는 `08_구현현황과_검증_2026-11-09.md`)

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

## 질문창·노트 다듬기 (Claude API, 선택)
키가 없어도 모든 기능이 정해진 양식으로 동작합니다. 키를 넣으면 질의응답과 인수인계 노트 문장 다듬기에 Claude를 씁니다.
```
backend\.env.example 을 backend\.env 로 복사한 뒤  ANTHROPIC_API_KEY=키  를 넣는다   (.env 는 git에 올라가지 않음)
.venv\Scripts\python -m agent.warm     # 발표용: 사전 질문 3개 답을 미리 저장
```
- 질의응답: Haiku 5.5, 읽기 전용 조회 도구로만 값을 가져오고, 답의 숫자가 도구 값과 맞는지 검사합니다(틀리면 1회 재시도, 그래도 틀리면 양식 답변). 점검 결과 기록은 제안만 만들고 사람이 확인 버튼을 눌러야 저장됩니다.
- 노트 문장 다듬기: Sonnet 5.5, 숫자·시각 값이 그대로인지 검사해 어긋난 구역은 양식 문장을 씁니다.
- 모델은 환경변수 `AGENT_MODEL_QA`, `AGENT_MODEL_NOTE`로 바꿀 수 있습니다.

## 테스트
```
cd backend
.venv\Scripts\python -m pytest -q
```
