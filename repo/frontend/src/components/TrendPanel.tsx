import type { DetectorState, Series } from "../types";
import Chart from "./Chart";
import { Card } from "./ui";

/** 시안의 '회수 유량 + 기준선 + 고정 임계값' 그래프. 사건은 그래프 위에 직접 표시한다. */
export default function TrendPanel({ series, detectors, currentTs, height = 230, title, caption }: {
  series: Series;
  detectors?: DetectorState;
  currentTs: number;
  height?: number;
  title?: string;
  caption?: string;
}) {
  const ew = detectors?.ewma_alarm_ts ?? null;
  const fx = detectors?.fixed_alarm_ts ?? null;
  const data = series.points.map((p) => ({ ts: p.ts, value: p.value, baseline: p.baseline }));
  const sub = `${series.name.replace(/^묶음 \d+ /, "")} (${series.unit})`;
  return (
    <Card title={title ?? `묶음 ${series.group + 1} ${sub}`} sub="실측 · 기준선 · 두 방식의 경보 시점" right="방식: 운전 조건 보정 모델 + 변화 탐지">
      <Chart
        includeZero
        data={data}
        lines={[
          { key: "value", color: "var(--chart-line)", width: 1.7 },
          { key: "baseline", color: "var(--chart-base)", width: 1.2, dash: "5 4" },
        ]}
        marks={[
          ...(ew != null ? [{ x: ew, kind: "tri" as const, color: "var(--watch)", label: "추세 감지 경보" }] : []),
          ...(fx != null ? [{ x: fx, kind: "sq" as const, color: "var(--alarm)", label: "고정 임계값 경보", labelSide: "below" as const }] : []),
        ]}
        xMax={Math.max(currentTs, 60)} xMin={Math.max(0, currentTs - 1440)} height={height} endLabel="실측" baseLabel="기준선" baseKey="baseline"
        bracket={ew != null && fx != null ? { x1: ew, x2: fx, label: `먼저 알게 된 시간 ${fx - ew}분` } : undefined}
      />
      <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px]" style={{ color: "var(--muted)" }}>
        <span><b style={{ color: "var(--chart-line)" }}>━</b> 실측(질량 기준)</span>
        <span><b style={{ color: "var(--chart-base)" }}>┅</b> 운전 조건 보정 기준선</span>
        <span><b style={{ color: "var(--watch)" }}>▲</b> 추세 감지 경보</span>
        <span><b style={{ color: "var(--alarm)" }}>■</b> 고정 임계값 경보</span>
      </div>
      <p className="mt-1 text-[14px]">
        {caption ?? (ew != null && fx != null
          ? <>추세 감지가 고정 임계값보다 <b>{fx - ew}분</b> 먼저 알렸습니다 (합성 데이터 기준).</>
          : ew != null
            ? <>추세 감지는 경보를 냈고, 고정 임계값 방식은 <b>아직 경보가 없습니다</b>.</>
            : "아직 경보가 없습니다.")}
      </p>
    </Card>
  );
}
