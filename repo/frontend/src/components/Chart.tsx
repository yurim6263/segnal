// 시안 스타일의 가벼운 SVG 꺾은선 그래프: 눈금은 최소, 선 끝에 이름, 사건은 마커+글자로 직접 표시.
export interface ChartLine { key: string; color: string; width?: number; dash?: string }

interface Props {
  data: Array<Record<string, number | null>>;
  lines: ChartLine[];
  xMax: number;
  height?: number;
  compact?: boolean;
  endLabel?: string;       // 마지막 점 옆 글자 (예: "실측")
  baseLabel?: string;      // 기준선 이름
  baseKey?: string;
  endKey?: string;
  xCaption?: string;       // 왼쪽 아래 글자
}


export default function Chart({ data, lines, xMax, height = 190, compact = false, endLabel, baseLabel, baseKey, endKey, xCaption }: Props) {
  const W = compact ? 300 : 760;
  const pk = endKey ?? lines[0].key;
  const ml = compact ? 38 : 44, mr = compact ? 8 : 92, mt = 14, mb = compact ? 6 : 24;
  const pw = W - ml - mr, ph = height - mt - mb;

  const vals: number[] = [];
  for (const d of data) for (const l of lines) { const v = d[l.key]; if (v != null && isFinite(v)) vals.push(v); }
  let lo = Math.min(...vals), hi = Math.max(...vals, lo + 1e-6);
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad; hi += pad;
  const X = (x: number) => ml + (Math.max(0, Math.min(xMax, x)) / xMax) * pw;
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
  const fmtT = (v: number) => (Math.abs(v) >= 10000 ? `${Math.round(v / 1000)}k` : Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : Math.abs(v) >= 1 ? v.toFixed(1) : v.toFixed(2));
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

      {lines.map((l) => (
        <path key={l.key} d={path(l.key)} fill="none" strokeLinejoin="round" strokeDasharray={l.dash} strokeWidth={l.width ?? 1.6} style={{ stroke: l.color }} />
      ))}
      {!compact && baseLabel && baseKey && (() => { const v = yAt(xMax, baseKey); return v == null ? null : <text x={ml + pw + 6} y={Y(v) + 4} style={txt}>{baseLabel}</text>; })()}

      {last && (
        <g>
          <circle cx={X(last.ts as number)} cy={Y(last[pk] as number)} r={3.5} style={{ fill: lines.find((l) => l.key === pk)?.color ?? lines[0].color }} />
          {endLabel && !compact && <text x={ml + pw + 6} y={Y(last[pk] as number) + 4} style={{ fill: "var(--text)", fontSize: 12, fontWeight: 700 }}>{endLabel}</text>}
        </g>
      )}
      {!compact && (
        <g>
          <text x={ml} y={height - 4} style={txt}>{xCaption}</text>
          {last && <text x={X(last.ts as number)} y={height - 4} textAnchor="middle" style={{ ...txt, fill: "var(--text)" }}>지금</text>}
        </g>
      )}
    </svg>
  );
}
