import { useEffect, useState } from "react";
import { api } from "../api";
import type { EvalSummary, Series, State } from "../types";
import TrendPanel from "../components/TrendPanel";
import { Card, PageHead, pct } from "../components/ui";

const locName = (k: string) => k.match(/\((.*)\)/)?.[1] ?? k;
const min = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v)}`);

function Kpi({ title, num, unit, lines }: { title: string; num: string; unit: string; lines: string[] }) {
  return (
    <div className="kpi">
      <div className="card-sub">{title}</div>
      <div className="mt-1"><span className="kpi-num">{num}</span><span className="kpi-unit">{unit}</span></div>
      {lines.map((l) => <div key={l} className="muted mt-0.5 text-[12.5px]">{l}</div>)}
    </div>
  );
}

function BarPair({ title, rows, unit }: { title: string; rows: { label: string; v: number; strong?: boolean }[]; unit: string }) {
  const max = Math.max(...rows.map((r) => r.v), 1e-9);
  return (
    <div className="mb-4 last:mb-0">
      <div className="mb-1.5 text-[13.5px] font-bold">{title}</div>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.label} className="grid grid-cols-[120px_1fr_64px] items-center gap-2 text-[13px]">
            <span style={{ fontWeight: r.strong ? 700 : 400 }}>{r.label}</span>
            <div className="bar-track" style={{ height: 11 }}><div className={`bar-fill ${r.strong ? "" : "bar-gray"}`} style={{ width: `${Math.max(2, (r.v / max) * 100)}%` }} /></div>
            <b className="text-right">{r.v >= 100 ? r.v.toFixed(0) : r.v >= 10 ? r.v.toFixed(1) : r.v.toFixed(2)}{unit}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function MetricsView({ state, series, ts }: { state: State | null; series: Series | null; ts: number }) {
  const [ev, setEv] = useState<EvalSummary | null | undefined>(undefined);
  useEffect(() => { api.evalSummary().then(setEv); }, []);

  if (ev === undefined) return <div><PageHead title="비교와 지표" /><Card><p className="muted">불러오는 중…</p></Card></div>;
  if (!ev) return <div><PageHead title="비교와 지표" /><Card><p className="muted">평가 결과를 불러오지 못했습니다. 백엔드를 실행했는지 확인하세요.</p></Card></div>;

  const o = ev.headline?.ours, f = ev.headline?.fixed;
  const ins = ev.inspection;
  const locEntry = ev.localize ? Object.values(ev.localize)[0] : null;
  const loc = locEntry?.weibull;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <PageHead title="비교와 지표" sub="앞선 시나리오에서 고정 임계값 방식과 우리 방식을 같은 조건으로 견준 결과입니다." />
        <p className="info-strip max-w-[420px] text-[13px]">가상 데이터로 검증했습니다. 경보 기준값은 가설이며, 현장 검증 전입니다.</p>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Kpi title="경보까지 걸린 시간" num={min(o?.median_delay_min)} unit="분" lines={[`고정 임계값 방식 ${min(f?.median_delay_min)}분`, `누수 ${o?.n ?? 0}건의 중앙값`]} />
        <Kpi title="정상인데 뜬 오경보" num={o ? o.false_alarms_per_14d_per_group.toFixed(2) : "—"} unit="회" lines={[`고정 임계값 방식 ${f ? f.false_alarms_per_14d_per_group.toFixed(2) : "—"}회`, f ? `다만 고정 방식은 ${f.n}건 중 ${f.missed}건을 놓침` : "", "누수 직전 구간 기준 · 장기 시험은 아래"].filter(Boolean)} />
        <Kpi title="확정까지 점검 횟수" num={ins ? ins.prob.mean_inspections.toFixed(1) : "—"} unit="회" lines={[`순서 없이 점검하면 ${ins ? ins.random.mean_inspections.toFixed(1) : "—"}회`, "후보 순서대로 점검할 때"]} />
        <Kpi title="위치 후보 적중률" num={loc ? pct(loc.group_top1) : "—"} unit="" lines={[`계측 묶음 1순위 기준`, loc ? `세그먼트 1순위 ${pct(loc.segment_top1)}` : ""].filter(Boolean)} />
        <Kpi title="원인 분류 정확도" num={ev.classify ? pct(ev.classify.accuracy) : "—"} unit="" lines={["누수·막힘·펌프 저하·센서 고장", "가상 시나리오 66건"]} />
      </div>

      <div className="mb-3 grid gap-3 lg:grid-cols-[1fr_380px]">
        <div className="min-w-0">
          {series && state ? (
            <TrendPanel series={series} detectors={state.alert.detectors} currentTs={ts} title="같은 누수, 다른 경보 시점"
              caption={state.alert.detectors.ewma_alarm_ts == null ? "재생 시각을 경보 이후로 옮기면 두 방식의 경보 시점이 함께 보입니다." : undefined} />
          ) : <Card title="같은 누수, 다른 경보 시점"><p className="muted">감시 화면에서 시나리오를 재생하면 표시됩니다.</p></Card>}
        </div>
        <Card title="비교" sub="막대가 짧을수록 좋음">
          {ins && (
            <BarPair title="확정까지 점검 횟수" unit="회" rows={[
              { label: "순서 없이", v: ins.random.mean_inspections },
              { label: "후보 순서대로", v: ins.prob.mean_inspections, strong: true },
              { label: "확신도÷부담 순", v: ins.o1.mean_inspections },
            ]} />
          )}
          {o && f && (
            <>
              <BarPair title="경보까지 걸린 시간" unit="분" rows={[
                { label: "고정 임계값", v: f.median_delay_min ?? 0 },
                { label: "추세 감지", v: o.median_delay_min ?? 0, strong: true },
              ]} />
              <BarPair title="정상인데 뜬 오경보" unit="회" rows={[
                { label: "고정 임계값", v: f.false_alarms_per_14d_per_group },
                { label: "추세 감지", v: o.false_alarms_per_14d_per_group, strong: true },
              ]} />
              <p className="muted text-[12.5px]">
                {o.false_alarms_per_14d_per_group > f.false_alarms_per_14d_per_group ? "오경보는 추세 감지가 더 많습니다. 대신 " : "오경보는 추세 감지가 같거나 더 적습니다. "}
                고정 임계값은 누수 {f.n}건 중 {f.missed}건을 아예 놓쳤습니다.
              </p>
            </>
          )}
        </Card>
      </div>

      {ev.longrun && (
        <Card title="오경보 장기 시험" sub={`정상 운전 ${ev.longrun.days_per_run}일 × ${ev.longrun.seeds}회를 이어서 돌린 결과`} right="공장 전체 · 월(30일) 환산" className="mb-3">
          <table className="tbl">
            <thead><tr><th>유량계 표류 가정</th><th>우리 방식 (경보 사건)</th><th>고정 임계값 (경보 사건)</th></tr></thead>
            <tbody>
              {ev.longrun.rows.map((r) => (
                <tr key={r.drift_scale} style={r.drift_scale === 1 ? { background: "var(--card2)" } : undefined}>
                  <td className="font-semibold">{r.label}</td>
                  <td style={r.ours_per_30d_plant > r.fixed_per_30d_plant * 2 ? { color: "var(--alarm)", fontWeight: 700 } : undefined}>월 {r.ours_per_30d_plant}건 <span className="muted">({r.ours_episodes}건/{r.days_total}일)</span></td>
                  <td>월 {r.fixed_per_30d_plant}건 <span className="muted">({r.fixed_episodes}건/{r.days_total}일)</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted mt-1 text-[12.5px]">
            "오경보 없음"은 누수 시작 전 1~1.5일 구간과 정상 3일에서 나온 값입니다. 오래 이어서 돌리면 현재 설정에서 두 방식이 비슷한 수준(월 수 건)이고, 유량계 표류가 크면 우리 방식이 더 민감해 경보가 급증합니다. 표류 크기는 현장에서 모르는 값이라 기준값을 주기적으로 다시 맞춰야 합니다.
          </p>
        </Card>
      )}

      <Card title="조건이 바뀔 때" sub="조건 하나씩 바꿔 가며 같은 지표를 다시 잡았습니다">
        {ev.sensitivity ? (
          <>
            <table className="tbl">
              <thead><tr><th>바꾼 조건</th><th>감지까지 걸린 시간</th><th>오경보 (14일·묶음당)</th><th>상위 3개 적중률</th><th>점검 횟수 (찾은 비율)</th></tr></thead>
              <tbody>
                {ev.sensitivity.rows.map((r) => {
                  const noisy = (r.false_alarms_per_14d_per_group ?? 0) > 3;
                  const base = r.key === "base";
                  return (
                    <tr key={r.key} style={base ? { background: "var(--card2)" } : undefined}>
                      <td className="font-semibold">{r.label}</td>
                      <td>
                        {r.median_delay_min == null ? "—" : <>{Math.round(r.median_delay_min)}분{noisy && <span className="muted" title="오경보가 많아 이 값은 의미가 약합니다"> *</span>}</>}
                        {r.missed > 0 && <span className="chip chip-watch ml-1.5" style={{ fontSize: 11.5 }}>{r.missed}/{r.n_leaks}건 놓침</span>}
                      </td>
                      <td style={noisy ? { color: "var(--alarm)", fontWeight: 700 } : undefined}>{r.false_alarms_per_14d_per_group == null ? "—" : `${r.false_alarms_per_14d_per_group.toFixed(2)}회`}</td>
                      <td>{r.top3_hit == null ? "—" : pct(r.top3_hit)}</td>
                      <td>{r.mean_inspections == null ? "—" : `${r.mean_inspections.toFixed(1)}회`}{r.inspection_success != null && <span className="muted"> ({pct(r.inspection_success)})</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="muted mt-1 text-[12.5px]">
              기준선과 경보 기준값은 그대로 두고 조건만 바꿨습니다(다시 맞추지 않은 경우). 같은 누수 {ev.sensitivity.n_cases}건을 조건마다 되풀이했고, 합성 데이터입니다. 적중률과 점검 횟수는 감지한 건만으로 계산했습니다.
              * 오경보가 많은 조건의 감지 시간은 잡음에 반응한 것이라 의미가 약합니다. 센서 잡음이 크게 늘면 기준값을 다시 맞춰야 합니다.
            </p>
          </>
        ) : <p className="muted text-[14px]">민감도 평가 결과가 없습니다. python -m eval.sensitivity_eval 을 실행하면 채워집니다.</p>}
      </Card>

      <div className="mt-3 space-y-2">
        <details className="card">
          <summary className="cursor-pointer text-[14.5px] font-bold">탐지 방식 전체 비교 <span className="card-sub">같은 데이터, 같은 오경보 기준</span></summary>
          <table className="tbl mt-2">
            <thead><tr><th>방식</th><th>놓침</th><th>중앙 지연</th><th>오경보</th></tr></thead>
            <tbody>{ev.detectors.map((d) => (
              <tr key={d.label}><td>{d.label}</td><td>{d.missed}/{d.n}</td><td>{d.median_delay_min == null ? "—" : `${Math.round(d.median_delay_min)}분`}</td><td>{d.false_alarms_per_14d_per_group.toFixed(2)}</td></tr>
            ))}</tbody>
          </table>
        </details>
        {ev.localize && (
          <details className="card">
            <summary className="cursor-pointer text-[14.5px] font-bold">위치 후보 정확도 <span className="card-sub">정답 위치가 후보 상위에 드는 비율</span></summary>
            <table className="tbl mt-2">
              <thead><tr><th>평가 조건</th><th>묶음 1순위</th><th>세그먼트 1순위</th><th>조인트 상위 10</th></tr></thead>
              <tbody>{Object.entries(ev.localize).map(([k, v]) => (
                <tr key={k}><td>{locName(k)}</td><td>{pct(v.weibull.group_top1)}</td><td>{pct(v.weibull.segment_top1)}</td><td>{pct(v.weibull.joint_top10)}</td></tr>
              ))}</tbody>
            </table>
            <p className="muted mt-1 text-[12.5px]">신호만으로는 계측 묶음까지는 잘 맞히지만 묶음 안의 세그먼트와 롤·조인트는 잘 구분하지 못합니다. 그래서 화면은 세그먼트 후보까지만 보여 주고 확정은 점검으로 합니다.</p>
          </details>
        )}
      </div>
    </div>
  );
}
