import pytest

from llm import policy, rag


@pytest.fixture(scope="module")
def idx():
    return rag.Index()


def test_chunks_have_metadata(idx):
    assert len(idx.chunks) > 30
    docs = {c.doc_id for c in idx.chunks}
    assert {"SPEC-01", "SOP-01", "SAF-01", "FORM-01", "HIST-01", "AC-01", "AC-06"} <= docs
    assert all(c.tier in policy.TIERS and c.roles for c in idx.chunks)


def test_permission_filter_before_search(idx):
    """권한 없는 조항은 어떤 질문에도 결과에 나오지 않는다."""
    queries = ["예비품 재고와 단가", "경보 한계 변경 승인자", "긴급 연락 담당자", "씰 교체 절차", "베어링 윤활", "수질 상한", "사례 담당자"]
    for role in policy.ROLES:
        for q in queries:
            for ch, _ in idx.search(role, q, k=50):
                assert policy.can_read_chunk(role, ch.tier, ch.roles), (role, q, ch.ref)
    for role in ("정비담당", "수처리담당"):
        assert not any(c.tier == "제한" for c, _ in idx.search(role, "예비품 재고와 단가 경보 한계 긴급 연락", k=100))
    assert any(c.ref == "SOP-01 7" for c, _ in idx.search("정비계획", "예비품 재고와 단가", k=5))


def test_water_role_scope(idx):
    docs = {idx.chunks[i].doc_id for i in idx.allowed("수처리담당")}
    assert "AC-05" in docs and "AC-02" in docs and "AC-03" not in docs and "HIST-01" not in docs


def test_retrieval_relevance(idx):
    top = idx.search("정비담당", "베어링 온도가 올랐을 때 계획 정지 조치", k=3, cause="BEARING")
    assert top and top[0][0].doc_id in ("AC-03", "SOP-01")
    top = idx.search("정비담당", "장착 후 압력 시험 방법", k=2)
    assert top[0][0].ref == "SOP-01 5"


def test_masking():
    t, n = policy.mask("담당: 박설비(사번 P10307, 내선 4311) 010-1234-5678 a.b@x.co.kr")
    assert n >= 4 and "박설비" not in t and "P10307" not in t and "4311" not in t and "5678" not in t
