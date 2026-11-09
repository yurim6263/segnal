import type { ReactNode } from "react";

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

export function Bar({ value }: { value: number }) {
  return <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></div>;
}
