# 연주기 세그먼트 냉각수 누수 예측·예방 — 해커톤 소스코드

세그먼트별 열화 신호(베어링 온도·진동, 냉각수 유량·압력), 운전 조건, 조인트 사용 기간으로 **다음 계획 정지 전 누수 확률과 유력 원인**을 예측하고, Claude가 그 근거로 **조치방안과 점검 작업지시서** 초안을 써서 누수를 미리 막는 시스템입니다. 최종 판단과 승인은 사람이 하고, 설비는 제어하지 않습니다. 팀 기준 문서는 `세그널_기획서_최종본.md`입니다. 기획서 기능과 구현의 매핑은 `03_팀_구현내용.md` §A에 있습니다.

> 모든 데이터는 **합성 데이터**이고 누수 생성 방식·전조 신호 가정 등 파라미터는 **가설**입니다. 효과는 시뮬레이션 기준입니다.

## 구성
```
config/plant.yaml   세그먼트 수명·누수 원인 시뮬레이터 가정 (현업 답변이 오면 여기만 수정)
backend/            FastAPI + 시뮬레이터 + 위험 예측·작업지시서·보안 LLM (Python 3.12)
frontend/           React + Vite + Tailwind 웹 대시보드
data/               합성 데이터(health/), SQLite 파일
docs/               가상 사내문서(corp/), 현업 질문 문안
```

## 실행
아래 명령은 저장소의 `repo` 폴더에서 시작합니다. 합성 데이터(`data/health/`)와 사내문서(`docs/corp/`)는 저장소에 들어 있어 따로 만들거나 적재하지 않아도 됩니다. 작업지시서·감사 기록 DB는 처음 쓸 때 자동으로 생깁니다.
```
# 1) 설치 (처음 한 번)
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd ..\frontend
npm install
cd ..

# 2) 실행: 백엔드와 프론트엔드를 새 창 두 개로 띄운다
run.bat
```
화면은 http://localhost:5173, API 문서는 http://localhost:8000/docs 입니다. `run.bat`은 설치된 환경을 확인하고 두 서버를 켜기만 하므로, 처음에는 1)을 먼저 해야 합니다.

`run.bat` 없이 직접 켜려면 터미널을 두 개 열어 각각 실행합니다.
```
# 터미널 1
cd backend
.venv\Scripts\python -m uvicorn main:app --reload --port 8000

# 터미널 2
cd frontend
npm run dev
```

1분 센서 시계열(`sensor_1min.csv`)은 위험 모델과 화면에서 쓰지 않아 실행에는 필요 없습니다. 용량이 커서(약 8MB) git에서 뺐고, 필요하면 `backend`에서 `.venv\Scripts\python -m sim.health_generate`로 만듭니다(시드 고정, 몇 초).

## 누수 위험 예측·보안 LLM (기획서 최종본 F3~F6)
```
cd backend
.venv\Scripts\python -m llm.build_docs              # 조치 카드 AC-01~06, 사례집 HIST-01 생성 (이미 있으면 건너뜀, 덮어쓰기는 --force). 문서는 docs/corp/*.md를 직접 수정
.venv\Scripts\python -m eval.risk_eval              # 위험 모델 이동 백테스트 → data/health/risk_eval.json
.venv\Scripts\python -m eval.redteam_eval --rules   # 공격 시험(모델 없이). --rules를 빼면 키가 있을 때 Claude 모드도 실행
.venv\Scripts\python -m eval.workorder_eval 7          # 작업지시서 자동 검증 통과율(Claude 호출 7회, 몇 분) → data/health/workorder_eval.json
```
- **주의:** 평가 명령은 `data/health/`의 결과 파일을 덮어씁니다. 키 없이 `eval.workorder_eval`을 돌리거나 `eval.redteam_eval --rules`를 돌리면 저장소에 있는 Claude 측정 결과가 사라집니다. 확인용으로 돌렸다면 커밋하기 전에 `repo` 폴더에서 `git restore data/health/workorder_eval.json data/health/redteam.json`으로 되돌립니다.
- 화면: `위험 예측`(순위판·작업지시서 생성·승인), `휴지 교체 계획`. 위쪽 `역할(데모)`을 바꾸면 AI가 받는 근거가 달라집니다.
- 질의응답(F8)은 지금 화면과 API에 연결되어 있지 않습니다. 게이트웨이 로직과 테스트는 `llm/gateway.py`, `tests/test_gateway.py`에 남아 있습니다.
- 사내문서는 `docs/corp/*.md`이고 조항 머리줄의 `{tier=등급 roles=역할 causes=원인코드}`가 권한과 검색 기준입니다. 검색은 권한 필터를 먼저 적용합니다.
- LLM 호출은 `llm/gateway.py`의 어댑터 한 곳을 거칩니다(사내 자체 LLM으로 교체 지점). 감사 로그 `data/audit.db`, 작업지시서 `data/workorders.db`는 git에 올라가지 않습니다.

## Claude API (선택)
키가 없어도 작업지시서가 규칙 기반 양식 모드로 동작합니다. 키를 넣으면 Claude가 초안을 씁니다.
```
backend\.env.example 을 backend\.env 로 복사한 뒤  ANTHROPIC_API_KEY=키  를 넣는다   (.env 는 git에 올라가지 않음)
```
- 작업지시서 모델은 환경변수 `AGENT_MODEL_NOTE`(기본 Sonnet 5.5)로 바꿀 수 있습니다.

## 테스트
```
cd backend
.venv\Scripts\python -m pytest -q
```
