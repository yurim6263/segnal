import type { PlantConfig, Series, State } from "../types";
import LineOverview from "../components/LineOverview";
import TrendPanel from "../components/TrendPanel";
import { AdviceCard, LeakSizeCard } from "../components/PatternCard";
import EarlyStrip from "../components/EarlyStrip";
import { Card, LEVEL_LABEL, LEVEL_VAR, StatusShape, groupName } from "../components/ui";

function GroupRow({ g }: { g: State["groups"][number] }) {
  const clamp = Math.max(-3, Math.min(3, g.deviation));
  const pos = ((clamp + 3) / 6) * 100;
  return (
    <div className="grid grid-cols-[72px_1fr_64px] items-center gap-2 py-1.5">
      <b className="text-[14.5px]">묶음 {groupName(g.segments)}</b>
      <div className="relative h-4">
        <div className="absolute top-1/2 h-px w-full" style={{ background: "var(--line)" }} />
        <div className="absolute top-0.5 h-3 w-px" style={{ left: "50%", background: "var(--muted)" }} />
        <div className="absolute top-1 h-2 w-px" style={{ left: "33.3%", background: "var(--line)" }} />
        <div className="absolute top-1 h-2 w-px" style={{ left: "66.6%", background: "var(--line)" }} />
        <div className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${pos}%`, background: "var(--primary)" }} />
      </div>
      <span className="flex items-center gap-1.5 text-[13.5px]" style={{ color: g.level === "normal" ? "var(--text)" : LEVEL_VAR[g.level] }}>
        <StatusShape level={g.level} />{LEVEL_LABEL[g.level]}
      </span>
    </div>
  );
}

export default function MonitorView({ config, state, series, ts }: { config: PlantConfig; state: State; series: Series; ts: number }) {
  const op = state.operating;
  return (
    <div>
      <EarlyStrip state={state} />
      {state.advice && <div className="mb-3"><AdviceCard a={state.advice} /></div>}
    <div className="grid gap-3 lg:grid-cols-[1fr_340px]">
      <div className="min-w-0 space-y-3">
        <Card title="라인 도면" sub={state.alert.level === "normal" ? "주의 구간 없음" : "주의 구간과 점검 후보"}>
          <LineOverview config={config} segments={state.segments} candidates={state.segment_candidates} impact={state.impact} />
        </Card>
        <TrendPanel series={series} detectors={state.alert.detectors} currentTs={ts} />
      </div>
      <div className="space-y-3">
        <LeakSizeCard est={state.leak_estimate} f={state.forecast} />
        <Card title="묶음 상태" sub="기준선 대비 편차">
          <div className="grid grid-cols-[72px_1fr_64px] gap-2 text-[12px] muted"><span /><span className="flex justify-between"><span>낮음</span><span>기준선</span><span>높음</span></span><span /></div>
          {state.groups.map((g) => <GroupRow key={g.group} g={g} />)}
          <p className="muted mt-2 text-[12.5px]">한 묶음만 벗어나면 누수 쪽, 여러 묶음이 함께 움직이면 펌프나 운전 조건을 먼저 의심합니다.</p>
        </Card>
        <Card title="운전 조건" sub="기준선을 계산할 때 쓰는 값">
          {op && (
            <dl className="grid grid-cols-[90px_1fr] items-center gap-y-2 text-[14.5px]">
              <dt className="muted">주조 속도</dt>
              <dd className="flex items-center gap-2"><b>{op.cast_speed.toFixed(2)} m/min</b>{op.changed_recently && <span className="chip chip-blue">방금 변경</span>}</dd>
              <dt className="muted">강종</dt><dd><span className="chip">{op.steel_grade}</span></dd>
              <dt className="muted">공급 온도</dt><dd><b>{op.t_in.toFixed(1)} ℃</b></dd>
            </dl>
          )}
        </Card>
        <Card title="이 화면이 판단하는 방법">
          <p className="text-[14px]">운전 조건으로 정상 값을 예측하고, 실측값과의 차이를 계속 봅니다.</p>
          <p className="muted mt-2 text-[14px]">유량이 낮아져도 운전 조건 때문이면 경보를 내지 않습니다. 차이가 한쪽으로 계속 벌어지면 주의를 알립니다.</p>
        </Card>
      </div>
    </div>
    </div>
  );
}
