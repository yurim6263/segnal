"""backend/.env 를 읽어 환경변수에 넣는다 (python-dotenv 없이). 이미 설정된 환경변수는 덮어쓰지 않는다.
키는 이 파일에만 두고 저장소에는 올리지 않는다(.gitignore). 키 값은 로그에 찍지 않는다."""
from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


MODEL_QA = lambda: os.environ.get("AGENT_MODEL_QA", "claude-haiku-5-5")        # 질의응답: 빠른 모델
MODEL_NOTE = lambda: os.environ.get("AGENT_MODEL_NOTE", "claude-sonnet-5-5")   # 작업지시서 초안
