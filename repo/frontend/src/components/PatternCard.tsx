import type { AdviceInfo, ForecastInfo, LeakEstimate, PatternInfo } from "../types";
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

const ACTION_LABEL: Record<AdviceInfo["action"], string> = { now: "지금 점검", next_break: "다음 휴지에 교체", watch: "감시 유지", verify: "원인 확인 먼저" };
const ACTION_COLOR: Record<AdviceInfo["action"], string> = { now: "var(--alarm)", next_break: "var(--watch)", watch: "var(--ok)", verify: "var(--muted)" };

/** 교체 시점 권고: 이 시스템의 결론 카드 */
export function AdviceCard({ a }: { a: AdviceInfo }) {
  const prog = a.progress != null ? Math.max(0, Math.min(1.2, a.progress)) : null;
  return (
    <Card title="교체 시점 권고" sub="누수가 맞다면 언제 무엇을 할지" right="방식: 추정 누수량 · 증가 추세 · 정비 창 비교" className="border-l-4" >
      <div className="flex flex-wrap items-start gap-3">
        <span className="rounded px-2.5 py-1 text-[14px] font-bold text-white" style={{ background: ACTION_COLOR[a.action] }}>{ACTION_LABEL[a.action]}</span>
        <p className="min-w-[260px] flex-1 text-[16px] font-bold leading-snug">{a.headline}</p>
      </div>
      {a.reasons.length > 0 && <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[13.5px]">{a.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_1fr]">
        <div className="space-y-2">
          {a.cases.map((c) => (
            <div key={c.label} className="rounded border p-2.5 text-[13.5px]" style={{ borderColor: "var(--line)", background: "var(--card2)" }}>
              <b>{c.label}</b><p className="mt-0.5">{c.text}</p>
            </div>
          ))}
        </div>
        <div className="text-[13.5px]">
          {prog != null && (
            <div>
              <p>추정 누수량 <b>{a.current_lpm?.toFixed(0)} L/min</b> · 교체 필요 크기({a.limit_lpm.toFixed(0)} L/min)의 <b>{Math.round((a.progress ?? 0) * 100)}%</b></p>
              <div className="relative mt-1 h-2.5 rounded" style={{ background: "var(--line)" }}>
                <div className="h-2.5 rounded" style={{ width: `${Math.min(prog, 1) * 100}%`, background: prog >= 1 ? "var(--alarm)" : "var(--primary)" }} />
              </div>
            </div>
          )}
          <dl className="mt-2.5 grid grid-cols-[88px_1fr] gap-y-1">
            <dt className="muted">다음 시퀀스 휴지</dt><dd>{a.next_break ? `${a.next_break.label} (${a.next_break.in_hours.toFixed(0)}시간 뒤)` : "—"}</dd>
            <dt className="muted">다음 계획 정지</dt><dd>{a.planned_stop ? `${a.planned_stop.label} (${a.planned_stop.in_hours.toFixed(0)}시간 뒤)` : "일정 없음"}</dd>
          </dl>
        </div>
      </div>
      <p className="mt-3 text-[12.5px]" style={{ color: "var(--watch)" }}>가정: {a.assumptions.join(" · ")}. 현업 답변이 오면 값만 바꿉니다. 도달 시간은 지금 속도가 이어진다는 직선 추세라 멈추면 닿지 않을 수 있습니다.</p>
    </Card>
  );
}

export function LeakSizeCard({ est, f }: { est?: LeakEstimate | null; f?: ForecastInfo | null }) {
  if (!est) return null;
  const prog = f?.progress != null ? Math.max(0, Math.min(1.2, f.progress)) : null;
  return (
    <Card title="추정 누수량" sub="최근 60분 평균, 상태와 별도로 표시">
      <p className="text-[22px] font-bold tabular-nums">약 {est.lpm.toFixed(0)} L/min <span className="muted text-[13.5px] font-normal">(범위 {est.low_lpm.toFixed(0)}~{est.high_lpm.toFixed(0)}, 입구 유량의 {est.pct.toFixed(2)}%)</span></p>
      {est.conditional && <p className="muted text-[12.5px]">원인이 구분되지 않아 "누수라면"의 값입니다.</p>}
      {prog != null && f?.limit_lpm != null && (
        <div className="mt-2">
          <p className="text-[13px]">교체 필요 크기({f.limit_lpm.toFixed(0)} L/min) 대비 <b>{Math.round((f.progress ?? 0) * 100)}%</b></p>
          <div className="relative mt-1 h-2.5 rounded" style={{ background: "var(--line)" }}>
            <div className="h-2.5 rounded" style={{ width: `${Math.min(prog, 1) * 100}%`, background: prog >= 1 ? "var(--alarm)" : "var(--primary)" }} />
          </div>
        </div>
      )}
    </Card>
  );
}
