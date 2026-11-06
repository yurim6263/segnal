// 시안 스타일의 가벼운 SVG 꺾은선 그래프: 눈금은 최소, 선 끝에 이름, 사건은 마커+글자로 직접 표시.
export interface ChartLine { key: string; color: string; width?: number; dash?: string }
export interface ChartHLine { y: number; label: string; color: string; dash?: string }
export interface ChartMark { x: number; kind: "tri" | "sq" | "dot"; color: string; label?: string; labelSide?: "above" | "below"; lineKey?: string }

interface Props {
  data: Array<Record<string, number | null>>;
  lines: ChartLine[];
  hlines?: ChartHLine[];
  marks?: ChartMark[];
  xMax: number;
  xMin?: number;
  height?: number;
  compact?: boolean;
  endLabel?: string;       // 마지막 점 옆 글자 (예: "실측")
  baseLabel?: string;      // 기준선 이름
  baseKey?: string;
  unit?: string;
  bracket?: { x1: number; x2: number; label: string };   // "먼저 알게 된 시간" 표시
  yDomain?: [number, number];
  endKey?: string;
  includeZero?: boolean;
}


export default function Chart({ data, lines, hlines = [], marks = [], xMax, xMin = 0, height = 190, compact = false, endLabel, baseLabel, baseKey, unit, bracket, yDomain, endKey, includeZero = false }: Props) {
  const W = compact ? 300 : 760;
  const pk = endKey ?? lines[0].key;
  const ml = compact ? 38 : 44, mr = compact ? 8 : 92, mt = 14, mb = compact ? 6 : 24;
  const pw = W - ml - mr, ph = height - mt - mb;

  const vals: number[] = [];
  data = data.filter((d) => (d.ts as number) >= xMin - 1);
  for (const d of data) for (const l of lines) { const v = d[l.key]; if (v != null && isFinite(v)) vals.push(v); }
  for (const h of hlines) vals.push(h.y);
  let lo = yDomain ? yDomain[0] : Math.min(...vals, ...(includeZero ? [0] : [])), hi = yDomain ? yDomain[1] : Math.max(...vals, ...(includeZero ? [0] : []), lo + 1e-6);
  if (!yDomain) { const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad; }
  const X = (x: number) => ml + ((Math.max(xMin, Math.min(xMax, x)) - xMin) / (xMax - xMin)) * pw;
  const Y = (y: number) => mt + (1 - (y - lo) / (hi - lo)) * ph;
  const path = (key: string) => {
    let s = "", pen = false;
    for (const d of data) {
      const v = d[key];
      if (v == null || !isFinite(v)) { pen = false; continue; }
      s += `${pen ? "L" : "M"}${X(d.ts as number).toFixed(1)},${Y(v).toFixed(1)}`;
      pen = true;
    }
    return s;
  };
  const yAt = (x: number, key?: string) => {
    const k = key ?? pk;
    let best: number | null = null, bd = Infinity;
    for (const d of data) { const v = d[k]; if (v == null) continue; const dist = Math.abs((d.ts as number) - x); if (dist < bd) { bd = dist; best = v; } }
    return best;
  };
  const niceTicks = (a: number, b: number, want: number) => {
    const raw = (b - a) / want, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 5, 10].map((m) => m * mag).find((x) => x >= raw) ?? raw;
    const out: number[] = [];
    for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(Math.abs(v) < step / 1e6 ? 0 : v);
    return out;
  };
  const ticks = niceTicks(lo, hi, compact ? 2 : 4);
  const fmtT = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : Math.abs(v) >= 1 ? v.toFixed(1) : v.toFixed(2));
  const halo = { stroke: "var(--card)", strokeWidth: 3.5, paintOrder: "stroke" } as const;
  const last = [...data].reverse().find((d) => d[pk] != null);
  const txt = { fill: "var(--muted)", fontSize: 11.5 } as const;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="w-full" style={{ display: "block" }} role="img">
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={ml} x2={ml + pw} y1={Y(t)} y2={Y(t)} style={{ stroke: "var(--chart-grid)" }} />
          <text x={ml - 5} y={Y(t) + 4} textAnchor="end" style={txt}>{fmtT(t)}</text>
        </g>
      ))}
      {unit && !compact && <text x={ml} y={10} style={txt}>{unit}</text>}

      {hlines.map((h) => (
        <g key={h.label}>
          <line x1={ml} x2={ml + pw} y1={Y(h.y)} y2={Y(h.y)} style={{ stroke: h.color }} strokeDasharray={h.dash ?? "5 4"} strokeWidth={1.3} />
          {!compact && <text x={ml + pw + 6} y={Y(h.y) + 4} style={{ fill: h.color, fontSize: 12 }}>{h.label}</text>}
        </g>
      ))}

      {lines.map((l) => (
        <path key={l.key} d={path(l.key)} fill="none" strokeLinejoin="round" strokeDasharray={l.dash} strokeWidth={l.width ?? 1.6} style={{ stroke: l.color }} />
      ))}
      {!compact && baseLabel && baseKey && (() => { const v = yAt(xMax, baseKey); return v == null ? null : <text x={ml + pw + 6} y={Y(v) + 4} style={txt}>{baseLabel}</text>; })()}

      {bracket && (
        <g style={{ stroke: "var(--muted)", fill: "var(--muted)" }}>
          <line x1={X(bracket.x1)} x2={X(bracket.x2)} y1={height - mb - 6} y2={height - mb - 6} strokeWidth={1.2} />
          <line x1={X(bracket.x1)} x2={X(bracket.x1)} y1={height - mb - 11} y2={height - mb - 1} strokeWidth={1.2} />
          <line x1={X(bracket.x2)} x2={X(bracket.x2)} y1={height - mb - 11} y2={height - mb - 1} strokeWidth={1.2} />
          <text x={(X(bracket.x1) + X(bracket.x2)) / 2} y={height - mb - 12} textAnchor="middle" style={{ fill: "var(--text)", fontSize: 12, ...halo }}>{bracket.label}</text>
        </g>
      )}

      {marks.map((m, i) => {
        if (m.x < xMin) return null;
        const v = yAt(m.x, m.lineKey);
        if (v == null) return null;
        const cx = X(m.x), cy = Y(v), c = m.color;
        const above = (m.labelSide ?? "above") === "above";
        return (
          <g key={i}>
            {m.kind === "tri" && <polygon points={`${cx},${cy - 6} ${cx + 6},${cy + 5} ${cx - 6},${cy + 5}`} style={{ fill: c }} />}
            {m.kind === "sq" && <rect x={cx - 5} y={cy - 5} width={10} height={10} style={{ fill: c }} />}
            {m.kind === "dot" && <circle cx={cx} cy={cy} r={4} style={{ fill: c }} />}
            {m.label && <text x={cx} y={above ? cy - 12 : cy + 20} textAnchor="middle" style={{ fill: "var(--text)", fontSize: 12, fontWeight: 700, ...halo }}>{m.label}</text>}
          </g>
        );
      })}

      {last && (
        <g>
          <circle cx={X(last.ts as number)} cy={Y(last[pk] as number)} r={3.5} style={{ fill: lines.find((l) => l.key === pk)?.color ?? lines[0].color }} />
          {endLabel && !compact && <text x={ml + pw + 6} y={Y(last[pk] as number) + 4} style={{ fill: "var(--text)", fontSize: 12, fontWeight: 700 }}>{endLabel}</text>}
        </g>
      )}
      {!compact && (
        <g>
          <text x={ml} y={height - 4} style={txt}>← 지난 {Math.round((xMax - xMin) / 60)}시간</text>
          {last && <text x={X(last.ts as number)} y={height - 4} textAnchor="middle" style={{ ...txt, fill: "var(--text)" }}>지금</text>}
        </g>
      )}
    </svg>
  );
}
