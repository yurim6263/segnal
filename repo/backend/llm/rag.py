"""사내문서 RAG. 조항 단위로 나누고, **권한 필터를 먼저 적용한 뒤** 검색한다.

- 문서는 docs/corp/*.md. 조항 머리줄 형식:  ## 5.2 제목 {tier=내부 roles=정비담당,관리자 causes=WEAR}
- 검색기는 교체 가능한 인터페이스(Retriever). 기본은 문자 n-gram TF-IDF(로컬, 외부 전송 없음). 사내 임베딩 모델로 바꾸려면 Retriever를 구현한다.
- 권한 없는 조항은 점수 계산에도 들어가지 않으므로 상위 결과에 섞일 수 없다(OWASP LLM08 대응).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from llm import policy

DOCS = Path(__file__).resolve().parents[2] / "docs" / "corp"
_HEAD = re.compile(r"^##\s+(\S+)\s+(.+?)\s*\{(.*)\}\s*$")


@dataclass
class Chunk:
    doc_id: str
    clause: str
    title: str
    text: str
    tier: str
    roles: list[str]
    causes: list[str]
    doc_title: str = ""

    @property
    def ref(self) -> str:
        return f"{self.doc_id} {self.clause}"


def _front(md: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", md, re.S)
    meta: dict = {}
    if m:
        for ln in m.group(1).splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                meta[k.strip()] = v.strip()
        md = md[m.end():]
    return meta, md


def load_chunks(dir_: Path | None = None) -> list[Chunk]:
    out: list[Chunk] = []
    for p in sorted((dir_ or DOCS).glob("*.md")):
        meta, body = _front(p.read_text(encoding="utf-8").replace("\r\n", "\n"))
        cur: Chunk | None = None
        buf: list[str] = []
        for ln in body.splitlines():
            m = _HEAD.match(ln)
            if m:
                if cur is not None:
                    cur.text = "\n".join(buf).strip()
                    out.append(cur)
                attrs = dict(a.split("=", 1) for a in m.group(3).split() if "=" in a)
                cur = Chunk(meta.get("doc_id", p.stem), m.group(1), m.group(2), "", attrs.get("tier", "내부"),
                            [r for r in attrs.get("roles", "").split(",") if r], [c for c in attrs.get("causes", "").split(",") if c],
                            meta.get("title", ""))
                buf = []
            elif cur is not None:
                buf.append(ln)
        if cur is not None:
            cur.text = "\n".join(buf).strip()
            out.append(cur)
    return out


class Retriever:
    """검색기 인터페이스. 허용된 조각만 받아 점수를 매긴다."""

    def fit(self, chunks: list[Chunk]) -> None:
        raise NotImplementedError

    def score(self, query: str, idx: list[int]) -> np.ndarray:
        raise NotImplementedError


class TfidfRetriever(Retriever):
    def __init__(self):
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.mat = None

    def fit(self, chunks):
        self.mat = self.vec.fit_transform([f"{c.doc_title} {c.title} {c.text}" for c in chunks])

    def score(self, query, idx):
        q = self.vec.transform([query])
        return (self.mat[idx] @ q.T).toarray().ravel()


class Index:
    def __init__(self, chunks: list[Chunk] | None = None, retriever: Retriever | None = None):
        self.chunks = chunks if chunks is not None else load_chunks()
        self.retriever = retriever or TfidfRetriever()
        self.retriever.fit(self.chunks)

    def allowed(self, role: str) -> list[int]:
        return [i for i, c in enumerate(self.chunks) if policy.can_read_chunk(role, c.tier, c.roles)]

    def search(self, role: str, query: str, k: int = 4, cause: str | None = None, doc_ids: list[str] | None = None) -> list[tuple[Chunk, float]]:
        idx = self.allowed(role)                      # 1) 권한 필터 먼저
        if doc_ids:
            idx = [i for i in idx if self.chunks[i].doc_id in doc_ids]
        if cause:                                     # 원인 코드가 맞는 조항 우선(없으면 전체)
            sel = [i for i in idx if cause in self.chunks[i].causes]
            idx = sel or idx
        if not idx:
            return []
        s = self.retriever.score(query, idx)          # 2) 허용된 조각만 점수 계산
        order = np.argsort(-s)[:k]
        return [(self.chunks[idx[j]], float(s[j])) for j in order if s[j] > 0]

    def get(self, ref: str, role: str) -> Chunk | None:
        for i in self.allowed(role):
            if self.chunks[i].ref == ref:
                return self.chunks[i]
        return None
