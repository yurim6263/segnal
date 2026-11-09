import type { ForecastInfo, LeakEstimate, PatternInfo } from "../types";
import { Card } from "./ui";

/** 신호가 평소 흔들림(σ)의 몇 배 움직였는지 가운데 기준으로 보여 준다. */
function SigmaRow({ label, sigma }: { label: string; sigma: number }) {
  const c = Math.max(-4, Math.min(4, sigma));
  const w = (Math.abs(c) / 4) * 50;
  const strong = Math.abs(sigma) >= 1.5;
  return (
    <div className="grid grid-cols-[132px_1fr_46px] items-center gap-2 py-[3px] text-[13px]">
      <span className={strong ? "font-semibold" : "muted"}>{label}</span>
      <div className="relative h-3.5">
        <div className="absolute left-0 right-0 top-1/2 h-px" style={{ background: "var(--line)" }} />
        <div className="absolute top-0 h-3.5 w-px" style={{ left: "50%", background: "var(--muted)" }} />
        <div className="absolute top-[3px] h-2 rounded-sm" style={{ left: c >= 0 ? "50%" : `${50 - w}%`, width: `${w}%`, background: strong ? "var(--primary)" : "var(--muted)", opacity: strong ? 1 : 0.55 }} />
      </div>
      <span className="text-right tabular-nums">{sigma > 0 ? "+" : ""}{sigma.toFixed(1)}σ</span>
    </div>
  );
}

export function PatternCard({ p }: { p: PatternInfo }) {
  return (
    <Card title="원인 구분 근거" sub="여러 신호가 움직인 방향을 고장별 모습과 비교" right="방식: 신호 방향 비교 (각도)">
      <div className="flex flex-wrap items-center gap-2">
        <b className="text-[15.5px]">{p.verdict}</b>
        {p.ambiguous && <span className="chip chip-dash">구분 불가</span>}
      </div>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <div>
          <p className="mb-1 text-[13px] font-semibold">가장 가까운 모습 <span className="muted font-normal">(사이각이 작을수록 가깝다)</span></p>
          <ul className="space-y-1.5">
            {p.ranking.map((r, i) => (
              <li key={r.cls} className="grid grid-cols-[1fr_70px] items-center gap-2 text-[13.5px]">
                <span className={i === 0 ? "font-semibold" : ""}>{i + 1}. {r.label}</span>
                <span className="text-right tabular-nums">{r.angle.toFixed(0)}°</span>
              </li>
            ))}
          </ul>
          <p className="muted mt-2 text-[12.5px]">1위와 2위의 차이는 {p.gap_deg.toFixed(0)}°입니다. 차이가 작으면 구분하지 않고 "구분 불가"로 남깁니다. 관측한 구간은 {p.window_min}분입니다.</p>
        </div>
        <div>
          <p className="mb-1 text-[13px] font-semibold">신호별 변화 <span className="muted font-normal">(평소 흔들림의 몇 배)</span></p>
          {p.signals.map((s) => <SigmaRow key={s.key} label={s.label} sigma={s.sigma} />)}
        </div>
      </div>
      <p className="info-strip mt-3 text-[13.5px]">확인 방법: {p.how_to_check}</p>
      <p className="muted mt-2 text-[12.5px]">기준 방향은 시뮬레이터에 고장을 주입해 얻었고, 펌프가 압력을 정하는 구조를 가정합니다. 밸브가 유량을 고정하는 구조라면 달라질 수 있어 현업 확인이 필요합니다.</p>
    </Card>
  );
}

export function ForecastCard({ f, est }: { f?: ForecastInfo | null; est?: LeakEstimate | null }) {
  if (!f && !est) return null;
  const prog = f?.progress != null ? Math.max(0, Math.min(1.2, f.progress)) : null;
  return (
    <Card title="누수량과 경보선 도달 예상" sub="상태(주의·경보)와 별도로 표시" right="방식: 불균형 추세 외삽">
      {est && (
        <div>
          <p className="muted text-[13px]">{est.conditional ? "누수라면 추정 누수량" : "추정 누수량"}</p>
          <p className="text-[22px] font-bold tabular-nums">약 {est.lpm.toFixed(0)} L/min <span className="muted text-[13.5px] font-normal">(범위 {est.low_lpm.toFixed(0)}~{est.high_lpm.toFixed(0)}, 입구 유량의 {est.pct.toFixed(2)}%)</span></p>
        </div>
      )}
      {prog != null && f?.line_leak_pct != null && (
        <div className="mt-3">
          <p className="text-[13px]">기존 방식 경보선 크기(입구 유량의 약 {f.line_leak_pct.toFixed(2)}%) 대비 <b>{Math.round((f.progress ?? 0) * 100)}%</b></p>
          <div className="relative mt-1 h-2.5 rounded" style={{ background: "var(--line)" }}>
            <div className="h-2.5 rounded" style={{ width: `${Math.min(prog, 1) * 100}%`, background: prog >= 1 ? "var(--alarm)" : "var(--primary)" }} />
          </div>
        </div>
      )}
      {f && (
        <div className="mt-3">
          <p className="text-[14.5px] font-semibold">{f.text}</p>
          <p className="muted mt-1 text-[12.5px]">누수가 지금 속도로 계속 커진다고 가정한 직선 추세입니다. 진행이 멈추거나 급변하면 닿지 않거나 더 빨라질 수 있습니다. 기울기가 뚜렷하지 않으면 시각을 내지 않습니다.</p>
        </div>
      )}
    </Card>
  );
}
