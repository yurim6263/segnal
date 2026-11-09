import { useEffect, useState } from "react";
import { api } from "../api";
import type { Series, State } from "../types";
import Chart from "../components/Chart";
import { LeakSizeCard, PatternCard } from "../components/PatternCard";
import { Bar, Card, NumBadge, PageHead, pct } from "../components/ui";

function trendText(s: Series | null): string {
  if (!s || s.points.length < 30) return "";
  const r = s.points.map((p) => (p.baseline == null ? 0 : p.value - p.baseline)).slice(-288);
  const half = Math.floor(r.length / 2);
  const early = r.slice(0, half), recent = r.slice(-12);
  const mean = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length;
  const sd = Math.sqrt(mean(early.map((x) => (x - mean(early)) ** 2))) || 1e-9;
  const d = mean(recent) - mean(early);
  if (Math.abs(d) < 3 * sd) return "변화 없음";
  return d < 0 ? "기준선보다 낮아져 있음" : "기준선보다 높아져 있음";
}

function Signal({ s }: { s: Series | null }) {
  const caption = trendText(s);
  return (
    <div className="min-w-0 flex-1">
      <div className="flex items-baseline justify-between gap-2"><b className="text-[14px]">{s ? s.name.replace(/^묶음 \d+ /, "") : "…"}</b><span className="card-sub">{s?.unit}</span></div>
      <div className="rounded border p-1" style={{ borderColor: "var(--line)", background: "var(--card2)" }}>
        {s ? <Chart compact height={92} xMax={Math.max(...s.points.map((p) => p.ts), 60)} xMin={Math.max(0, Math.max(...s.points.map((p) => p.ts)) - 1440)}
          data={s.points.map((p) => ({ ts: p.ts, value: p.value, baseline: p.baseline }))}
          lines={[{ key: "value", color: "var(--chart-line)", width: 1.3 }, { key: "baseline", color: "var(--chart-base)", width: 1, dash: "4 3" }]} /> : <div style={{ height: 96 }} />}
      </div>
      <p className="mt-1 text-[13px] font-semibold" style={{ color: caption === "변화 없음" ? "var(--muted)" : "var(--primary)" }}>{caption}</p>
    </div>
  );
}

export default function DiagnosisView({ state, scenarioId, ts, imbSeries }: { state: State; scenarioId: string; ts: number; imbSeries: Series }) {
  const g = state.alert.group ?? imbSeries.group;
  const [sigs, setSigs] = useState<Record<string, Series | null>>({ m_in: null, p_out: null, p_in: null });
  useEffect(() => {
    let alive = true;
    (["m_in", "p_out", "p_in"] as const).forEach((ch) => api.series(scenarioId, g, ts, ch).then((s) => alive && setSigs((o) => ({ ...o, [ch]: s }))));
    return () => { alive = false; };
  }, [scenarioId, g, ts]);

  const top3 = state.segment_candidates.filter((c) => c.prob > 0.005).slice(0, 3);
  const level = state.alert.level;
  const topSeg = top3[0]?.segment ?? null;
  const inside = state.candidates.filter((c) => c.segment === topSeg).slice(0, 3);
  const insideSum = inside.reduce((a, c) => a + c.prior, 0) || 1;
  const ew = state.alert.detectors.ewma_alarm_ts;
  const headline = level === "normal" ? "진단: 지금은 이상 징후가 없습니다" : "진단: 왜 주의인지, 어디가 의심되는지";

  return (
    <div>
      <PageHead title={headline} sub="결론은 후보와 확신도까지이고, 확정은 점검으로 합니다." />
      <div className="grid gap-3 lg:grid-cols-[1fr_380px]">
        <div className="min-w-0 space-y-3">
          {state.pattern && <PatternCard p={state.pattern} />}
          <Card title="원인 분류" sub="누수·계측기 오차·막힘·펌프 저하 중 어느 쪽에 가까운가" right="방식: 규칙 + 신호 방향 비교 (현장 확인 전 가설)">
            <table className="tbl">
              <thead><tr><th style={{ width: 70 }}>원인</th><th>이런 모습이면</th><th>지금 신호</th><th style={{ width: 90 }}>판정</th></tr></thead>
              <tbody>
                {state.cause_table.map((r) => (
                  <tr key={r.cause}>
                    <td className="font-bold">{r.label}</td><td>{r.pattern}</td><td>{r.now}</td>
                    <td>{r.verdict.includes("후보") ? <span className="chip chip-blue">✓ {r.verdict}</span> : <span className="muted">{r.verdict}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted mt-1 text-[12.5px]">σ는 정상 구간의 변동 크기입니다. 판정 기준값은 현장 확인 전 가설입니다.</p>
          </Card>

          <Card title="신호 세 가지" sub={`묶음 ${g + 1}, 회색 점선이 기준선`}>
            <div className="flex flex-col gap-3 md:flex-row">
              <Signal s={sigs.m_in} /><Signal s={sigs.p_out} /><Signal s={sigs.p_in} />
            </div>
          </Card>

          <Card title="기준선과의 차이" sub="실측에서 예측을 뺀 값" right="방식: 운전 조건 보정 모델 + 변화 탐지(EWMA)">
            <Chart
              includeZero height={190} xMax={Math.max(ts, 60)} xMin={Math.max(0, ts - 1440)} unit="차이 (%)"
              data={imbSeries.points.map((p) => ({ ts: p.ts, residual: p.residual, ewma: p.ewma }))}
              lines={[{ key: "residual", color: "var(--chart-base)", width: 1 }, { key: "ewma", color: "var(--chart-line)", width: 2 }]}
              hlines={imbSeries.ewma_limit != null ? [{ y: imbSeries.ewma_limit, label: "관리 한계", color: "var(--alarm)" }] : []}
              marks={ew != null ? [{ x: ew, kind: "tri", color: "var(--watch)", label: "추세 감지 경보", lineKey: "ewma" }] : []}
              endLabel="평활한 차이" endKey="ewma"
            />
            <div className="muted mt-1 flex gap-5 text-[12.5px]"><span>━ 평활한 차이</span><span>━ 차이 원값(회색)</span><span style={{ color: "var(--alarm)" }}>┄ 관리 한계</span></div>
          </Card>
        </div>

        <div className="space-y-3">
          <LeakSizeCard est={state.leak_estimate} f={state.forecast} />
          <Card title="위치 후보" sub={`확신도가 높은 순 · 묶음 ${g + 1} 안의 세그먼트`} right="방식: 서명 매칭 + 확률 갱신">
            {top3.length === 0 ? (
              <p className="muted text-[14px]">{level === "normal" ? "이상 징후가 없어 후보가 없습니다." : state.alert.cause === "ambiguous" ? "누수인지 계측기 오차인지 구분되지 않아 위치 후보를 만들지 않습니다." : "누수로 판정된 경우에만 위치 후보를 만듭니다."}</p>
            ) : (
              <ul className="space-y-3">
                {top3.map((c) => (
                  <li key={c.segment}>
                    <div className="flex items-center gap-2">
                      <NumBadge n={c.rank} on={c.rank === 1} />
                      <b className="text-[16px]">세그먼트 {c.segment}</b>
                      <span className="ml-auto text-[13px]">{state.distinguishable ? "확신도" : "가능성"} <b>{pct(c.prob)}</b></span>
                    </div>
                    <div className="mt-1.5"><Bar value={c.prob} /></div>
                    {c.evidence.map((e, i) => <p key={i} className="muted mt-1 text-[12.5px]">{e}</p>)}
                  </li>
                ))}
              </ul>
            )}
            {top3.length > 0 && <p className="muted mt-3 text-[13px]">그 밖의 세그먼트 합계 <b>{pct(state.others_prob)}</b></p>}
            {state.candidate_note && <p className="info-strip mt-2 text-[13px]">{state.candidate_note}</p>}
          </Card>

          {inside.length > 0 && topSeg != null && (
            <Card title={`세그먼트 ${topSeg} 안의 후보`} sub="롤과 조인트 순서" right="방식: 수명 사전확률(Weibull)">
              <ul className="space-y-2.5">
                {inside.map((c) => (
                  <li key={c.id} className="grid grid-cols-[110px_1fr_44px] items-center gap-2 text-[13.5px]">
                    <span>롤 {c.roll} · {c.side === "in" ? "입구" : "출구"}</span><Bar value={c.prior / insideSum} /><span className="text-right">{pct(c.prior / insideSum)}</span>
                  </li>
                ))}
              </ul>
              <p className="muted mt-2 text-[12.5px]">계측이 묶음 단위이면 여기까지 좁히지 못합니다. 이 순서는 신호가 아니라 조인트의 사용 기간(수명 모델)으로 정한 것이고, 확정은 점검으로 합니다.</p>
            </Card>
          )}

          <Card title="전체 신호" sub="계측이 있을 때만 표시">
            <dl className="space-y-1.5 text-[14px]">
              <div className="flex items-center justify-between"><dt className="font-semibold">보충수 유량</dt><dd className="chip chip-dash muted">계측 여부 확인 필요</dd></div>
              <div className="flex items-center justify-between"><dt className="font-semibold">탱크 수위</dt><dd className="chip chip-dash muted">계측 여부 확인 필요</dd></div>
            </dl>
            <p className="muted mt-2 text-[12.5px]">현업 답변을 받으면 이 두 신호를 근거에 더합니다.</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
