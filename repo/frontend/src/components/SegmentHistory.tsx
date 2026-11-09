// 세그먼트의 일별 신호 추세와 정비 이력(data/health 의 합성 데이터). 점선은 같은 날 장착 세그먼트 평균.
import Chart from "./Chart";
import { Card } from "./ui";
import type { SegmentHistoryData } from "../llmApi";

const TRENDS = [
  { key: "bearing_t_avg_c", label: "베어링 온도", unit: "℃" },
  { key: "vib_rms_mm_s", label: "베어링 진동", unit: "mm/s" },
  { key: "low_flow_min", label: "유량 90% 미만 시간", unit: "분/일" },
  { key: "pressure_events", label: "압력 급변", unit: "회/일" },
  { key: "t_out_avg_c", label: "회수수 온도", unit: "℃" },
  { key: "joint_age_t", label: "씰·조인트 교체 후 누적", unit: "t" },
];
const HERO_SIGNAL: Record<string, string> = { HAMMER: "low_flow_min", WEAR: "joint_age_t" };   // 유력 원인을 가장 잘 보여 주는 신호. 나머지는 베어링 온도
const PART: Record<string, string> = { seal: "씰", rotary_joint: "로터리 조인트", bearing: "베어링", hose: "호스", oring: "O링", roll: "롤", bearing_housing: "베어링 하우징" };
const TYPE: Record<string, string> = { replace: "교체", inspect: "점검", leak_repair: "누수 수리" };

function TrendChart({ h, signal, compact = false, height }: { h: SegmentHistoryData; signal: string; compact?: boolean; height?: number }) {
  const data = h.days.map((d, i) => ({ ts: i, v: d[signal] as number | null, fleet: d[`fleet_${signal}`] as number | null }));
  if (!data.some((p) => p.v != null)) return <p className="muted py-6 text-center text-[13px]">{signal === "vib_rms_mm_s" ? "진동 센서 없음" : "최근 기록 없음"}</p>;
  return (
    <Chart data={data} xMax={data.length - 1} compact={compact} height={height} endKey="v" endLabel={h.segment} baseLabel="장착 평균" baseKey="fleet" xCaption={`← 지난 ${data.length}일`}
      lines={[{ key: "fleet", color: "var(--bar-gray)", dash: "5 4", width: 1.4 }, { key: "v", color: "var(--chart-line)", width: 2.4 }]} />
  );
}

export function HeroTrend({ h, cause }: { h: SegmentHistoryData; cause: string }) {
  const t = TRENDS.find((x) => x.key === (HERO_SIGNAL[cause] ?? "bearing_t_avg_c"))!;
  return (
    <div className="min-h-0 flex-1 p-2" style={{ background: "var(--card2)", border: "1px solid var(--chart-grid)" }}>
      <div className="muted text-[12.5px]">{h.segment} {t.label}({t.unit}) · 점선은 같은 날 장착 평균</div>
      <TrendChart h={h} signal={t.key} height={195} />
    </div>
  );
}

export default function SegmentHistory({ h, causeLabel }: { h: SegmentHistoryData; causeLabel: Record<string, string> }) {
  const latest = (key: string) => {
    const row = [...h.days].reverse().find((d) => d[key] != null);
    return row ? (row[key] as number).toLocaleString() : "—";
  };
  return (
    <>
      <Card className="mt-3" title={`${h.segment} 최근 ${h.days.length}일 신호`} sub="점선은 같은 날 장착 세그먼트 평균 · 끊긴 구간은 탈거 기간">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {TRENDS.map((t) => (
            <div key={t.key} className="p-2" style={{ background: "var(--card2)", border: "1px solid var(--chart-grid)" }}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="muted text-[13px]">{t.label}</span>
                <span><b className="mono text-[15px]">{latest(t.key)}</b> <span className="muted text-[12px]">{t.unit}</span></span>
              </div>
              <TrendChart h={h} signal={t.key} compact height={104} />
            </div>
          ))}
        </div>
      </Card>
      <Card className="mt-3" title={`${h.segment} 정비 이력`} sub="최근 10건">
        {h.maintenance.length === 0 ? <p className="muted text-[14px]">기록이 없습니다.</p> : (
          <div className="overflow-x-auto"><table className="tbl">
            <thead><tr><th>날짜</th><th>부품</th><th>종류</th><th>씰 마모 등급</th><th>확인 원인</th><th>작업지시서</th></tr></thead>
            <tbody>{h.maintenance.map((m, i) => (
              <tr key={i}><td className="mono text-[13px]">{m.date}</td><td>{PART[m.part] ?? m.part}</td><td>{TYPE[m.type] ?? m.type}</td><td>{m.finding_grade ?? "—"}</td>
                <td>{m.found_cause ? causeLabel[m.found_cause] ?? m.found_cause : "—"}</td><td className="mono text-[13px]">{m.wo_id ?? "—"}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
    </>
  );
}
