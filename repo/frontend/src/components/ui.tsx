import type { ReactNode } from "react";
import type { Level } from "../types";

export const LEVEL_LABEL: Record<Level, string> = { normal: "정상", watch: "주의", alarm: "경보" };
export const LEVEL_VAR: Record<Level, string> = { normal: "var(--ok)", watch: "var(--watch)", alarm: "var(--alarm)" };
export const LEVEL_COLOR = LEVEL_VAR;

/** 색만으로 구분되지 않도록 정상=원, 주의=삼각형, 경보=사각형을 함께 쓴다. */
export function StatusShape({ level, size = 12 }: { level: Level; size?: number }) {
  const c = LEVEL_VAR[level];
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true" style={{ flex: "none" }}>
      {level === "normal" && <circle cx="7" cy="7" r="6" style={{ fill: c }} />}
      {level === "watch" && <polygon points="7,1 13,13 1,13" style={{ fill: c }} />}
      {level === "alarm" && <rect x="1.5" y="1.5" width="11" height="11" style={{ fill: c }} />}
    </svg>
  );
}

export function StatusChip({ level }: { level: Level }) {
  return (
    <span className="chip" style={{ borderColor: LEVEL_VAR[level], fontWeight: 600, fontSize: 13.5, padding: "3px 10px" }}>
      <StatusShape level={level} />
      {LEVEL_LABEL[level]}
    </span>
  );
}
export const StatusBadge = StatusChip;

export function Card({ title, sub, right, children, className = "" }: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <div className="flex flex-wrap items-baseline gap-2">
            {title && <h3 className="card-title">{title}</h3>}
            {sub && <span className="card-sub">{sub}</span>}
          </div>
          {right && <span className="card-sub">{right}</span>}
        </div>
      )}
      {children}
    </section>
  );
}
/** 예전 이름 호환: method는 오른쪽 "방식:" 표기 */
export function Panel({ title, method, children, className = "" }: { title: string; method?: string; children: ReactNode; className?: string }) {
  return <Card title={title} right={method ? `방식: ${method}` : undefined} className={className}>{children}</Card>;
}

export function PageHead({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-[20px] font-bold">{title}</h2>
      {sub && <p className="muted text-[14px]">{sub}</p>}
    </div>
  );
}

export function NumBadge({ n, on = false }: { n: number; on?: boolean }) {
  return <span className={`num-badge ${on ? "on" : ""}`}>{n}</span>;
}

export function Bar({ value, gray = false }: { value: number; gray?: boolean }) {
  return <div className="bar-track"><div className={`bar-fill ${gray ? "bar-gray" : ""}`} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></div>;
}

export const fmtTime = (ts: number) =>
  `${Math.floor(ts / 1440) + 1}일차 ${String(Math.floor((ts % 1440) / 60)).padStart(2, "0")}:${String(ts % 60).padStart(2, "0")}`;
export const fmtElapsed = (ts: number) => `${String(Math.floor(ts / 60)).padStart(2, "0")}:${String(ts % 60).padStart(2, "0")}`;
export const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`;
export const groupName = (g: number[]) => (g.length > 1 ? `${Math.min(...g)}–${Math.max(...g)}` : `${g[0]}`);

/** 숫자 뒤 조사: 받침이 있으면 a(을/이), 없으면 b(를/가). 읽는 법 기준(1·3·6·7·8·0으로 끝나면 받침 있음) */
export const josa = (n: number, a: string, b: string) => ([0, 1, 3, 6, 7, 8].includes(n % 10) ? a : b);
