// 연주기 단면 도면(시안 D): 호 안쪽 빈 공간에 children(결론 패널)을 얹는다. 칸 색과 글자는 넘겨받은 값으로만 그린다.
import type { KeyboardEvent, ReactNode } from "react";

export interface ArcCell { position: number; bundle: string; serial: string; prob: number; tone: "hot" | "warm" | "plain" }

const W = 1400, H = 670, CX = 560, CY = 110, ROLL_R = 470, RAD = Math.PI / 180;
const X_STRAIGHT = 572, LEN_STRAIGHT = 720, Y_STRAIGHT = 580;
const LABEL = "'Gothic A1','Malgun Gothic',sans-serif", MONO = "'JetBrains Mono',Consolas,monospace";
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

export default function CasterArc({ cells, focus, focusLabel, onSelect, ariaLabel, children }: {
  cells: ArcCell[]; focus?: number | null; focusLabel?: string; onSelect?: (position: number) => void; ariaLabel: string; children?: ReactNode;
}) {
  const n = cells.length, nCurve = Math.ceil(n / 2), step = 90 / nCurve, pitch = LEN_STRAIGHT / (n - nCurve);
  const curved = (p: number) => p <= nCurve;
  const polar = (r: number, deg: number) => ({ x: CX - r * Math.cos(deg * RAD), y: CY + r * Math.sin(deg * RAD) });
  const sx = (p: number) => X_STRAIGHT + pitch * (p - nCurve - 0.5) - 12;
  const cellW = (p: number) => (curved(p) ? ROLL_R * step * RAD * 0.8 : pitch - 24);
  const at = (p: number) => (curved(p) ? { ...polar(ROLL_R, (p - 0.5) * step), rot: 90 - (p - 0.5) * step } : { x: sx(p), y: Y_STRAIGHT, rot: 0 });

  const bundles = [...new Set(cells.map((c) => c.bundle))].map((id) => {
    const ps = cells.filter((c) => c.bundle === id).map((c) => c.position);
    return { id, lo: Math.min(...ps), hi: Math.max(...ps), max: Math.max(...cells.filter((c) => c.bundle === id).map((c) => c.prob)) };
  });
  const focusCell = cells.find((c) => c.position === focus);
  const anchor = (b: { lo: number; hi: number }) => {
    const mid = (b.lo + b.hi) / 2;
    return curved(b.hi) ? { ...polar(400, (mid - 0.5) * step), align: "start" as const } : { x: sx(mid), y: 500, align: "middle" as const };
  };
  const band = (b: { lo: number; hi: number }) => {
    if (!curved(b.hi)) return `M ${sx(b.lo) - cellW(b.lo) / 2} 622 H ${sx(b.hi) + cellW(b.hi) / 2}`;
    const a = polar(512, (b.lo - 1) * step), z = polar(512, b.hi * step);
    return `M ${a.x} ${a.y} A 512 512 0 0 0 ${z.x} ${z.y}`;
  };
  const key = (e: KeyboardEvent, p: number) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect?.(p); } };

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="group" aria-label={ariaLabel}>
        <defs>
          <linearGradient id="caster-strand" gradientUnits="userSpaceOnUse" x1="90" y1="0" x2="1320" y2="0">
            <stop offset="0" stopColor="#FFA23A" /><stop offset=".3" stopColor="#E5561C" /><stop offset=".68" stopColor="#8C5A48" /><stop offset="1" stopColor="#737C85" />
          </linearGradient>
        </defs>
        <g strokeWidth={1.4} style={{ fill: "var(--seg-fill)", stroke: "var(--line-strong)" }}>
          <polygon points="52,6 128,6 118,32 62,32" /><polygon points="44,40 136,40 124,62 56,62" /><rect x="74" y="72" width="32" height="30" />
        </g>
        <g fontSize={12.5} fontFamily={LABEL} style={{ fill: "var(--muted)" }}>
          <text x="136" y="24">래들</text><text x="144" y="56">턴디시</text><text x="114" y="92">몰드</text>
        </g>

        <path d="M 38 66 V 110 A 522 522 0 0 0 560 632 H 1290" fill="none" strokeWidth={3} style={{ stroke: "var(--water)" }} />
        <path d="M 24 66 V 110 A 536 536 0 0 0 560 646 H 1290" fill="none" strokeWidth={2} strokeDasharray="7 6" style={{ stroke: "var(--water)" }} />
        {focusCell && <path d={band(bundles.find((b) => b.id === focusCell.bundle)!)} fill="none" strokeWidth={9} style={{ stroke: "var(--watch)" }} />}

        <path d="M 90 102 V 110 A 470 470 0 0 0 560 580 H 1290" fill="none" stroke="url(#caster-strand)" strokeWidth={15} />
        <path d="M 114 110 A 446 446 0 0 0 560 556 H 1290" fill="none" strokeWidth={5} strokeLinecap="round" strokeDasharray="0 15" style={{ stroke: "var(--line-strong)" }} />
        <path d="M 66 110 A 494 494 0 0 0 560 604 H 1290" fill="none" strokeWidth={5} strokeLinecap="round" strokeDasharray="0 15" style={{ stroke: "var(--line-strong)" }} />

        {cells.map((c) => {
          const p = at(c.position), w = cellW(c.position), selected = c.position === focus;
          const fill = c.tone === "hot" ? "var(--watch)" : c.tone === "warm" ? "var(--watch-soft)" : "var(--seg-fill)";
          const stroke = selected ? "var(--text)" : c.tone === "plain" ? "var(--seg-stroke)" : "var(--watch)";
          return (
            <g key={c.position} onClick={() => onSelect?.(c.position)} onKeyDown={(e) => key(e, c.position)} tabIndex={onSelect ? 0 : undefined}
              role={onSelect ? "button" : undefined} aria-label={`${c.position}번 자리 ${c.serial} ${pct(c.prob)}`} style={{ cursor: onSelect ? "pointer" : "default" }}>
              <title>{`${c.serial} · ${c.position}번 자리 · ${pct(c.prob)}`}</title>
              <rect x={-w / 2} y={-19} width={w} height={38} transform={`translate(${p.x} ${p.y}) rotate(${p.rot})`} strokeWidth={selected ? 2.6 : 1.4} style={{ fill, stroke }} />
              <text x={p.x} y={p.y + 5.5} textAnchor="middle" fontFamily={MONO} fontSize={16} fontWeight={700} style={{ fill: c.tone === "hot" ? "var(--primary-fg)" : "var(--text)" }}>{c.position}</text>
            </g>
          );
        })}

        {bundles.map((b) => {
          const a = anchor(b);
          if (focusCell?.bundle === b.id) {
            return (
              <g key={b.id} textAnchor={a.align} style={{ fill: "var(--watch-fg)" }}>
                <text x={a.x} y={a.y} fontFamily={LABEL} fontSize={15} fontWeight={800}>▲ {focusLabel}</text>
                <text x={a.x} y={a.y + 32} fontFamily={MONO} fontSize={29} fontWeight={700}>{pct(focusCell.prob)}</text>
              </g>
            );
          }
          return (
            <text key={b.id} x={a.x} y={a.y} textAnchor={a.align} fontFamily={LABEL} fontSize={13.5} style={{ fill: "var(--muted)" }}>
              <tspan fontSize={15} fontWeight={700} style={{ fill: "var(--text)" }}>묶음 {b.id}</tspan> {pct(b.max)}
            </text>
          );
        })}

        <path d={`M ${X_STRAIGHT} 543 V 537 H 1268 V 543`} fill="none" strokeWidth={1.2} style={{ stroke: "var(--line-strong)" }} />
        <line x1="1296" x2="1296" y1="546" y2="614" strokeWidth={1.6} style={{ stroke: "var(--seg-stroke)" }} />
        <text x="1296" y="538" textAnchor="middle" fontFamily={LABEL} fontSize={12.5} style={{ fill: "var(--muted)" }}>절단</text>
        <rect x="1308" y="572" width="34" height="16" style={{ fill: "var(--slab)" }} /><rect x="1350" y="572" width="34" height="16" style={{ fill: "var(--slab)" }} />
        <text x="1282" y="627" textAnchor="end" fontFamily={LABEL} fontSize={12.5} style={{ fill: "var(--water)" }}>공급</text>
        <text x="1282" y="663" textAnchor="end" fontFamily={LABEL} fontSize={12.5} style={{ fill: "var(--water)" }}>회수 (점선)</text>
      </svg>
      {children && (
        <section className="arc-panel card mt-3 flex flex-col gap-3 xl:absolute xl:left-[30.86%] xl:top-[2.7%] xl:mt-0 xl:h-[67.5%] xl:w-[67.57%]" style={{ padding: "18px 22px" }}>{children}</section>
      )}
    </div>
  );
}
