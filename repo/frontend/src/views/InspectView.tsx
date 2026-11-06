import { useEffect, useState } from "react";
import type { PlantConfig, State } from "../types";
import LineOverview from "../components/LineOverview";
import { Card, NumBadge, PageHead, fmtTime, josa, pct } from "../components/ui";

interface Props {
  config: PlantConfig;
  state: State;
  onInspect: (segment: number, result: "leak_confirmed" | "no_issue") => void;
  onDelete: (id: number) => void;
}

type Snap = { n: number; ranks: Record<number, number> };

export default function InspectView({ config, state, onInspect, onDelete }: Props) {
  const [sel, setSel] = useState<number | null>(null);
  const confirmed = state.confirmed_segment;
  const pending = state.segment_candidates.filter((c) => !c.inspected && c.prob > 0.005);
  const order = [...pending].sort((a, b) => a.priority_rank - b.priority_rank).slice(0, 5);
  const next = order[0] ?? null;
  const target = sel ?? next?.segment ?? null;
  const targetCand = state.segment_candidates.find((c) => c.segment === target) ?? null;
  const targetDone = state.inspections.find((i) => i.segment === target);

  // 점검 결과를 넣기 전 순위를 기억해 "이전 N순위"를 보인다
  const nIns = state.inspections.length;
  const ranksKey = order.map((c) => `${c.segment}:${c.priority_rank}`).join(",");
  const [snaps, setSnaps] = useState<{ cur: Snap; prev: Snap | null }>({ cur: { n: nIns, ranks: {} }, prev: null });
  useEffect(() => {
    const ranks: Record<number, number> = {};
    order.forEach((c) => { ranks[c.segment] = c.priority_rank; });
    setSnaps((s) => (s.cur.n === nIns ? { cur: { n: nIns, ranks }, prev: s.prev } : { cur: { n: nIns, ranks }, prev: nIns > s.cur.n ? s.cur : null }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nIns, ranksKey]);
  const prevRank = (seg: number) => snaps.prev?.ranks[seg];
  const last = state.inspections[state.inspections.length - 1];

  if (state.alert.level === "normal" && nIns === 0) {
    return (
      <div>
        <PageHead title="점검: 지금은 점검할 곳이 없습니다" sub="감시 화면에서 주의가 나타나면 이곳에 점검 순서가 만들어집니다." />
        <Card><p className="muted text-[14.5px]">정상 상태입니다. 후보가 없어서 점검 순서를 만들지 않았습니다.</p></Card>
      </div>
    );
  }

  const rankNote = (() => {
    if (!targetCand || !snaps.prev) return null;
    const p = prevRank(targetCand.segment);
    if (p == null) return `점검 결과를 반영해 후보에 새로 올라왔습니다.`;
    if (p !== targetCand.priority_rank) return `${last ? `세그먼트 ${last.segment}${josa(last.segment, "이", "가")} 빠지면서 ` : ""}${p}순위에서 ${targetCand.priority_rank}순위로 올라왔습니다. 확신도도 다시 계산했습니다.`;
    return null;
  })();

  return (
    <div>
      <PageHead title={confirmed != null ? `점검: 세그먼트 ${confirmed}에서 누수를 확인했습니다` : "점검: 확신도가 높은 곳부터"} sub="점검 결과를 넣으면 남은 후보의 순위를 다시 계산합니다." />
      {last && confirmed == null && (
        <div className="info-strip mb-3">
          <b>세그먼트 {last.segment}{josa(last.segment, "을", "를")} {last.result === "no_issue" ? "이상 없음" : "누수 확인"}으로 기록했습니다.</b>
          {next && <> 남은 후보의 순위를 다시 계산했고, 세그먼트 {next.segment}{josa(next.segment, "이", "가")} 1순위가 되었습니다.</>}
        </div>
      )}
      <div className="grid gap-3 lg:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-3">
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="card-sub">점검할 곳</div>
                {target == null ? <div className="muted mt-1">도면에서 칸을 눌러 선택하세요.</div> : (
                  <>
                    <div className="mt-0.5 flex flex-wrap items-center gap-3">
                      <span className="text-[26px] font-bold">세그먼트 {target}</span>
                      {targetCand && !targetCand.inspected && <span className="chip chip-blue">후보 {targetCand.priority_rank}순위</span>}
                      {targetCand && <span className="text-[14px]">{state.distinguishable ? "확신도" : "가능성"} <b>{pct(targetCand.prob)}</b></span>}
                    </div>
                    {targetCand?.evidence[0] && <p className="muted mt-1 max-w-[520px] text-[13.5px]">근거: {targetCand.evidence[0]}</p>}
                    {targetCand && <p className="muted text-[13px]">점검 약 {targetCand.inspect_minutes}분 · 접근 위험 {targetCand.access_risk}</p>}
                    {rankNote && <p className="mt-1 text-[13.5px]" style={{ color: "var(--primary)" }}>{rankNote}</p>}
                  </>
                )}
              </div>
              <div>
                <div className="card-sub mb-1.5">점검 결과</div>
                {target != null && targetDone ? (
                  <p className="text-[14px]">기록됨: <b>{targetDone.result === "leak_confirmed" ? "누수 확인" : "이상 없음"}</b></p>
                ) : (
                  <div className="flex gap-2">
                    <button className="btn" style={{ minWidth: 140, padding: "12px 16px" }} disabled={target == null || confirmed != null} onClick={() => target != null && onInspect(target, "no_issue")}>이상 없음</button>
                    <button className="btn" style={{ minWidth: 140, padding: "12px 16px" }} disabled={target == null || confirmed != null} onClick={() => target != null && onInspect(target, "leak_confirmed")}>누수 확인</button>
                  </div>
                )}
              </div>
            </div>
          </Card>

          <Card title="라인 도면" sub="점검 위치 · 칸을 눌러 다른 곳을 고를 수 있습니다">
            <LineOverview config={config} segments={state.segments} candidates={state.segment_candidates}
              nowSegment={confirmed == null ? next?.segment ?? null : null} selectedSegment={sel} onSelectSegment={setSel} />
          </Card>
        </div>

        <div className="space-y-3">
          <Card title="점검 순서" sub="확신도가 높은 순">
            {confirmed != null ? (
              <p className="text-[14px]">세그먼트 {confirmed}에서 누수를 확인했습니다. 더 점검할 곳이 없습니다.</p>
            ) : order.length === 0 ? (
              <p className="muted text-[14px]">남은 후보가 없습니다. 기록이 틀렸다면 고쳐 주세요.</p>
            ) : (
              <ul className="space-y-2.5">
                {order.map((c, i) => {
                  const p = prevRank(c.segment);
                  return (
                    <li key={c.segment} className="flex items-center gap-2.5">
                      <NumBadge n={c.priority_rank} on={i === 0} />
                      <div className="min-w-0 flex-1">
                        <b>세그먼트 {c.segment}</b>
                        {snaps.prev && (p != null && p !== c.priority_rank ? <span className="muted ml-2 text-[12px]">이전 {p}순위</span> : p == null ? <span className="ml-2 text-[12px]" style={{ color: "var(--primary)" }}>새로 올라옴</span> : null)}
                        {c.priority_rank !== c.rank && <div className="muted text-[11.5px]">확신도는 {c.rank}위지만 점검 부담이 {c.priority_rank < c.rank ? "작아 앞당김" : "커 뒤로 미룸"}</div>}
                      </div>
                      <span className="text-[13px]">{pct(c.prob)}</span>
                      <span className="w-8 text-right text-[12.5px]" style={{ color: i === 0 ? "var(--primary)" : "var(--muted)", fontWeight: i === 0 ? 700 : 400 }}>{i === 0 ? "지금" : "대기"}</span>
                    </li>
                  );
                })}
              </ul>
            )}
            {state.inspections.filter((i) => i.result === "no_issue").map((i) => (
              <div key={i.id} className="mt-2.5 flex items-center gap-2.5 text-[13.5px]">
                <span className="num-badge" style={{ borderColor: "var(--muted)", color: "var(--muted)" }}>✓</span>
                <b className="muted">세그먼트 {i.segment}</b><span className="muted ml-auto text-[12.5px]">점검함, 이상 없음</span>
              </div>
            ))}
          </Card>

          <Card title="점검 기록" sub={nIns ? `${nIns}건` : undefined}>
            {nIns === 0 ? (
              <div className="dashed-box">아직 기록이 없습니다. 결과를 넣으면 시각, 위치, 결과가 여기에 쌓입니다.</div>
            ) : (
              <ul className="space-y-2">
                {state.inspections.map((i) => (
                  <li key={i.id} className="flex items-center gap-2 text-[13.5px]">
                    <span className="muted w-[78px] text-[12px]">{i.sim_ts != null ? fmtTime(i.sim_ts).replace("일차 ", "일 ") : ""}</span>
                    <b>세그먼트 {i.segment}</b>
                    <span className="ml-auto" style={{ color: i.result === "leak_confirmed" ? "var(--alarm)" : "var(--muted)", fontWeight: i.result === "leak_confirmed" ? 700 : 400 }}>
                      {i.result === "leak_confirmed" ? "■ 누수 확인" : "이상 없음"}
                    </span>
                    <button className="btn btn-sm" onClick={() => onDelete(i.id)}>고치기</button>
                  </li>
                ))}
              </ul>
            )}
            {state.minutes_since_alarm != null && confirmed != null && (
              <p className="info-strip mt-3 text-[13.5px]">경보 뒤 <b>{state.minutes_to_confirm ?? state.minutes_since_alarm}분</b>, 점검 <b>{nIns}회</b> 만에 확인했습니다.</p>
            )}
          </Card>

          <Card title="알아둘 것">
            <p className="text-[13.5px]">이 화면은 점검할 곳과 순서를 권고합니다. 점검은 현장 절차에 따릅니다.</p>
            <p className="muted mt-2 text-[13.5px]">결과를 잘못 넣으면 순위가 틀어집니다. 잘못 넣은 결과는 점검 기록에서 고칠 수 있습니다.</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
