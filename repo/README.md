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
```
# 1) 백엔드 (처음 한 번)
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
# 세그먼트 수명·누수 원인 데이터(기획서 5-1): 대부분의 CSV는 data/health/에 들어 있다.
# 용량이 커서(약 8MB) git에서 뺀 1분 센서 시계열(sensor_1min.csv)은 아래 명령으로 만든다 (시드 고정, 몇 초).
.venv\Scripts\python -m sim.health_generate
# 서버
.venv\Scripts\python -m uvicorn main:app --reload --port 8000

# 2) 프론트엔드 (처음 한 번 npm install)
cd frontend
npm install
npm run dev      # http://localhost:5173
```
`run.bat`이 위 실행을 한 번에 합니다.

## 누수 위험 예측·보안 LLM (기획서 최종본 F3~F6, F8)
```
cd backend
.venv\Scripts\python -m llm.build_docs              # 조치 카드 AC-01~06, 사례집 HIST-01 생성 (이미 있으면 건너뜀, 덮어쓰기는 --force). 문서는 docs/corp/*.md를 직접 수정
.venv\Scripts\python -m eval.risk_eval              # 위험 모델 이동 백테스트 → data/health/risk_eval.json
.venv\Scripts\python -m eval.redteam_eval --rules   # 공격 시험(모델 없이). --rules를 빼면 키가 있을 때 Claude 모드도 실행
.venv\Scripts\python -m eval.workorder_eval 7          # 작업지시서 자동 검증 통과율(Claude 호출 7회, 몇 분) → data/health/workorder_eval.json
```
- 화면: `위험 예측`(순위판·작업지시서 생성·승인), `휴지 교체 계획`. 위쪽 `역할(데모)`을 바꾸면 AI가 받는 근거가 달라집니다.
- 사내문서는 `docs/corp/*.md`이고 조항 머리줄의 `{tier=등급 roles=역할 causes=원인코드}`가 권한과 검색 기준입니다. 검색은 권한 필터를 먼저 적용합니다.
- LLM 호출은 `llm/gateway.py`의 어댑터 한 곳을 거칩니다(사내 자체 LLM으로 교체 지점). 감사 로그 `data/audit.db`, 작업지시서 `data/workorders.db`는 git에 올라가지 않습니다.

## Claude API (선택)
키가 없어도 질의응답·작업지시서가 규칙 기반 양식 모드로 동작합니다. 키를 넣으면 두 기능에 Claude를 씁니다.
```
backend\.env.example 을 backend\.env 로 복사한 뒤  ANTHROPIC_API_KEY=키  를 넣는다   (.env 는 git에 올라가지 않음)
```
- 모델은 환경변수 `AGENT_MODEL_QA`(질의응답, 기본 Haiku 5.5), `AGENT_MODEL_NOTE`(작업지시서, 기본 Sonnet 5.5)로 바꿀 수 있습니다.

## 테스트
```
cd backend
.venv\Scripts\python -m pytest -q
```
