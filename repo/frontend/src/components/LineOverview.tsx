// 연주기 라인 도면 (시안 형태): 래들 → 턴디시 → 몰드 → 휘어진 구간 → 수평 구간 → 절단.
// 칸 수·계측 묶음은 /api/config 값으로 그린다(하드코딩 없음). 색은 모두 CSS 변수.
// 주의 구간은 칸 하나가 아니라 계측 묶음 전체에 띠로 긋는다(계측이 묶음 단위이므로).
import type { ImpactRange, PlantConfig, SegmentCandidate, SegmentStatus } from "../types";
import { groupName } from "./ui";

interface Props {
  config: PlantConfig;
  segments: SegmentStatus[];
  candidates: SegmentCandidate[];
  impact?: ImpactRange | null;
  nowSegment?: number | null;
  selectedSegment?: number | null;
  onSelectSegment?: (s: number) => void;
  showLegend?: boolean;
}

const R = 150, X0 = 80, Y0 = 122, CELL = 48;

export default function LineOverview({ config, segments, candidates, impact, nowSegment, selectedSegment, onSelectSegment, showLegend = true }: Props) {
  const n = config.n_segments;
  const nCurved = Math.ceil(n / 2), nStraight = n - nCurved;
  const cx = X0 + R, cy = Y0, yb = cy + R;
  const xEnd = cx + nStraight * CELL;
  const W = xEnd + 140, H = yb + 62;

  const pos = (s: number) => {
    const i = s - 1;
    if (i < nCurved) {
      const th = Math.PI - ((i + 0.5) / nCurved) * (Math.PI / 2);
      const ang = Math.atan2(-Math.cos(th), Math.sin(th));
      return { x: cx + R * Math.cos(th), y: cy + R * Math.sin(th), ang, ix: -Math.cos(th), iy: -Math.sin(th), half: (R * Math.PI) / 2 / nCurved / 2, curved: true };
    }
    return { x: cx + (i - nCurved + 0.5) * CELL, y: yb, ang: 0, ix: 0, iy: -1, half: CELL / 2, curved: false };
  };
  const st = (s: number) => segments.find((x) => x.segment === s);
  const cand = (s: number) => candidates.find((c) => c.segment === s);
  const level = (s: number) => st(s)?.level ?? "normal";
  const anyWatch = segments.some((s) => s.level === "watch");
  const anyAlarm = segments.some((s) => s.level === "alarm");
  const live = candidates.filter((c) => c.rank <= 3 && c.prob > 0.02 && !c.inspected);
  const anyCand = live.length > 0;
  const anyLow = live.some((c) => c.rank > 1);
  const anyDone = segments.some((s) => s.inspected === "no_issue");
  const confirmed = segments.find((s) => s.inspected === "leak_confirmed")?.segment ?? null;

  const rr = (k: number) => R + k;
  const supply = `M ${X0 - 22} ${Y0 - 28} V ${Y0} A ${rr(22)} ${rr(22)} 0 0 0 ${cx} ${yb + 22} H ${xEnd + 6}`;
  const ret = `M ${X0 - 30} ${Y0 - 28} V ${Y0} A ${rr(30)} ${rr(30)} 0 0 0 ${cx} ${yb + 30} H ${xEnd + 6}`;
  const lineColor = (lv: string) => (lv === "alarm" ? "var(--alarm)" : "var(--watch)");

  return (
    <div>
    <div className="flex flex-col gap-3 md:flex-row">
      <svg viewBox={`0 0 ${W} ${H}`} className="min-w-0 flex-1" role="img" aria-label="연주기 기계 냉각수 라인 도면" style={{ maxHeight: 400 }}>
        {/* 래들 · 턴디시 · 몰드 */}
        <g style={{ fill: "var(--card2)", stroke: "var(--seg-stroke)" }} strokeWidth={1.4}>
          <polygon points={`${X0 - 30},8 ${X0 + 30},8 ${X0 + 22},30 ${X0 - 22},30`} />
          <polygon points={`${X0 - 34},38 ${X0 + 34},38 ${X0 + 26},58 ${X0 - 26},58`} />
          <rect x={X0 - 11} y={68} width={22} height={22} />
        </g>
        <g style={{ fill: "var(--muted)", fontSize: 12 }}>
          <text x={X0 + 40} y={24}>래들</text><text x={X0 + 44} y={52}>턴디시</text><text x={X0 + 22} y={84}>몰드</text>
        </g>
        <line x1={X0} x2={X0} y1={90} y2={Y0} style={{ stroke: "var(--seg-stroke)" }} strokeWidth={2} />

        {/* 냉각수 공급(실선) / 회수(점선) */}
        <path d={supply} fill="none" style={{ stroke: "var(--primary)" }} strokeWidth={2} />
        <path d={ret} fill="none" style={{ stroke: "var(--primary)" }} strokeWidth={1.6} strokeDasharray="5 4" />
        <text x={xEnd + 4} y={yb + 54} textAnchor="end" style={{ fill: "var(--primary)", fontSize: 12.5, fontWeight: 700 }}>기계 냉각수 회로</text>

        {/* 절단 · 슬래브 */}
        <line x1={xEnd + 10} x2={xEnd + 10} y1={yb - 22} y2={yb + 22} style={{ stroke: "var(--seg-stroke)" }} strokeWidth={1.4} />
        <text x={xEnd + 10} y={yb - 28} textAnchor="middle" style={{ fill: "var(--muted)", fontSize: 12 }}>절단</text>
        {[0, 1, 2].map((i) => <rect key={i} x={xEnd + 24 + i * 36} y={yb - 5} width={30} height={10} rx={1} style={{ fill: "var(--slab)" }} />)}

        {/* 계측 묶음: 이름 글자 + 주의/경보 띠 */}
        {config.sensor_groups.map((g, gi) => {
          const lv = g.map(level).includes("alarm") ? "alarm" : g.map(level).includes("watch") ? "watch" : "normal";
          const mid = pos(g[Math.floor((g.length - 1) / 2)]);
          const lx = mid.x + mid.ix * 72, ly = mid.y + mid.iy * 72;
          return (
            <g key={gi}>
              {lv !== "normal" && g.map((s) => {
                const p = pos(s);
                const bx = p.x + p.ix * 44, by = p.y + p.iy * 44;
                const tx = Math.cos(p.ang), ty = Math.sin(p.ang);
                return <line key={s} x1={bx - tx * p.half} y1={by - ty * p.half} x2={bx + tx * p.half} y2={by + ty * p.half} style={{ stroke: lineColor(lv) }} strokeWidth={4} strokeLinecap="butt" />;
              })}
              <text x={lx} y={ly + 4} textAnchor="middle" style={{ fill: lv === "normal" ? "var(--muted)" : lv === "alarm" ? "var(--alarm)" : "var(--watch-fg)", fontSize: 12.5, fontWeight: lv === "normal" ? 400 : 700 }}>
                {lv === "watch" ? "▲ 주의: " : lv === "alarm" ? "■ 경보: " : ""}{lv === "normal" ? groupName(g) : `묶음 ${groupName(g)}`}
              </text>
            </g>
          );
        })}

        {/* 세그먼트 칸 */}
        {Array.from({ length: n }, (_, i) => i + 1).map((s) => {
          const p = pos(s), c = cand(s), s0 = st(s);
          const rank = c && c.rank <= 3 && c.prob > 0.02 && !c.inspected ? c.rank : null;
          const done = s0?.inspected === "no_issue";
          const leak = s0?.inspected === "leak_confirmed";
          const isNow = nowSegment === s, sel = selectedSegment === s;
          const w = p.curved ? 26 : 38, h = 26;
          let fill = "var(--seg-fill)", stroke = "var(--seg-stroke)", text = "var(--text)";
          if (leak) { fill = "var(--alarm)"; stroke = "var(--alarm)"; text = "#fff"; }
          else if (rank === 1 || isNow) { fill = "var(--primary)"; stroke = "var(--primary)"; text = "var(--primary-fg)"; }
          else if (rank != null) { fill = "var(--primary-soft)"; stroke = "var(--primary)"; text = "var(--primary-soft-fg)"; }
          return (
            <g key={s} onClick={() => onSelectSegment?.(s)} style={{ cursor: onSelectSegment ? "pointer" : "default" }}>
              <g transform={`translate(${p.x} ${p.y}) rotate(${(p.ang * 180) / Math.PI})`}>
                <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={2} style={{ fill, stroke: sel ? "var(--text)" : stroke }} strokeWidth={sel ? 2.4 : 1.3} strokeDasharray={done ? "3 3" : undefined} />
              </g>
              <text x={p.x} y={p.y + 4.5} textAnchor="middle" style={{ fill: done ? "var(--muted)" : text, fontSize: 13, fontWeight: 600 }}>{s}</text>
              {rank != null && (
                <g>
                  <circle cx={p.x + p.ix * 27} cy={p.y + p.iy * 27} r={8.5} style={{ fill: "var(--card)", stroke: "var(--primary)" }} strokeWidth={1.4} />
                  <text x={p.x + p.ix * 27} y={p.y + p.iy * 27 + 4} textAnchor="middle" style={{ fill: "var(--primary)", fontSize: 11.5, fontWeight: 700 }}>{rank}</text>
                </g>
              )}
            </g>
          );
        })}
      </svg>

      {showLegend && (
        <ul className="flex shrink-0 flex-col gap-1.5 text-[12.5px] md:w-[170px]">
          <LegendBox label="정상" />
          {anyWatch && <LegendLine color="var(--watch)" label="주의 구간" />}
          {anyAlarm && <LegendLine color="var(--alarm)" label="경보 구간" />}
          {(anyCand || nowSegment != null) && <LegendBox fill="var(--primary)" stroke="var(--primary)" label={nowSegment != null ? "지금 점검할 곳" : "후보 1순위"} />}
          {anyLow && <LegendBox fill="var(--primary-soft)" stroke="var(--primary)" label="후보 2–3순위" />}
          {anyDone && <LegendBox dashed label="점검함, 이상 없음" />}
          {confirmed != null && <LegendBox fill="var(--alarm)" stroke="var(--alarm)" label="누수 확인" />}
          <li className="mt-1 flex items-center gap-2"><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" style={{ stroke: "var(--primary)" }} strokeWidth={2} /></svg>냉각수 공급</li>
          <li className="flex items-center gap-2"><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" style={{ stroke: "var(--primary)" }} strokeWidth={1.6} strokeDasharray="4 3" /></svg>냉각수 회수</li>
        </ul>
      )}
    </div>
    {impact && <p className="muted mt-1 text-[12.5px]">영향 슬래브 구간(검사 대상 후보): 몰드 출구로부터 {impact.start_m}~{impact.end_m} m</p>}
    </div>
  );
}

function LegendBox({ label, fill = "var(--seg-fill)", stroke = "var(--seg-stroke)", dashed = false }: { label: string; fill?: string; stroke?: string; dashed?: boolean }) {
  return (
    <li className="flex items-center gap-2">
      <svg width="22" height="14"><rect x="1" y="1" width="20" height="12" rx="1.5" style={{ fill: dashed ? "none" : fill, stroke }} strokeWidth={1.3} strokeDasharray={dashed ? "3 3" : undefined} /></svg>
      {label}
    </li>
  );
}
function LegendLine({ color, label }: { color: string; label: string }) {
  return <li className="flex items-center gap-2"><svg width="22" height="14"><line x1="0" x2="22" y1="7" y2="7" style={{ stroke: color }} strokeWidth={4} /></svg>{label}</li>;
}
