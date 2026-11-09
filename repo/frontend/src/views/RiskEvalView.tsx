import { useEffect, useState } from "react";
import { Bar, Card, PageHead } from "../components/ui";
import { llm, type RiskEval } from "../llmApi";

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const num = (x: number | null) => (x == null ? "—" : x.toFixed(2));

function Compare({ rows }: { rows: { label: string; text: string; value: number; gray?: boolean }[] }) {
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[110px_1fr_64px] items-center gap-3 text-[14px]">
          <span className={r.gray ? "muted" : "font-bold"}>{r.label}</span><Bar value={r.value} gray={r.gray} /><b className="mono text-right">{r.text}</b>
        </li>
      ))}
    </ul>
  );
}

export default function RiskEvalView() {
  const [d, setD] = useState<RiskEval | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { llm.riskEval().then(setD).catch((e) => setErr(e.message)); }, []);
  if (err) return <Card title="위험 모델 검증"><p className="muted">{err}</p></Card>;
  if (!d) return <Card title="위험 모델 검증"><p className="muted">불러오는 중…</p></Card>;

  const m = d.with_vibration, noBearing = d.no_bearing_sensor;
  const label = (c: string) => d.coefficients.find((x) => x.cause === c)?.label ?? c;
  const causes = [...m.per_cause_auc].sort((a, b) => b.n - a.n);
  const maxN = Math.max(...causes.map((c) => c.n), 1);
  const maxRate = Math.max(...m.calibration.flatMap((b) => [b.pred_mean, b.obs_rate]));
  const [lo, hi] = m.auc_diff_90ci;

  return (
    <div>
      <PageHead title="위험 모델 검증" sub={`같은 합성 데이터에서 기존 톤수 순과 비교한 백테스트입니다. 누수 ${m.leaks}건이라 범위가 넓습니다.`} />
      <div className="grid gap-3 md:grid-cols-2">
        <Card title="누수 구분 능력 (AUC)" sub={`차이의 90% 범위 ${lo >= 0 ? "+" : ""}${lo.toFixed(2)} ~ ${hi >= 0 ? "+" : ""}${hi.toFixed(2)}`}>
          <Compare rows={[{ label: "이 모델", text: m.auc_model.toFixed(3), value: m.auc_model }, { label: "톤수 순", text: m.auc_tons_order.toFixed(3), value: m.auc_tons_order, gray: true }]} />
        </Card>
        <Card title="매일 위험 상위 3개에 실제 누수가 든 비율">
          <Compare rows={[{ label: "이 모델", text: pct(m.top3_daily_capture_model), value: m.top3_daily_capture_model }, { label: "톤수 순", text: pct(m.top3_daily_capture_tons), value: m.top3_daily_capture_tons, gray: true }, { label: "무작위", text: pct(m.top3_daily_capture_random), value: m.top3_daily_capture_random, gray: true }]} />
        </Card>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <div className="kpi"><div className="muted text-[12.5px]">유력 원인 1순위 적중</div><span className="kpi-num">{pct(m.cause_top1_acc)}</span></div>
        <div className="kpi"><div className="muted text-[12.5px]">베어링 센서가 없을 때 AUC</div><span className="kpi-num">{noBearing.auc_model.toFixed(3)}</span></div>
        <div className="kpi"><div className="muted text-[12.5px]">베어링 센서가 없을 때 원인 적중</div><span className="kpi-num">{pct(noBearing.cause_top1_acc)}</span></div>
      </div>

      <Card className="mt-3" title="위험도 보정" sub="예측 확률이 낮은 구간부터 5등분. 하루 단위 확률이라 값이 작습니다">
        <div className="overflow-x-auto"><table className="tbl">
          <thead><tr><th>구간</th><th style={{ width: "34%" }}>평균 예측</th><th style={{ width: "34%" }}>실제 누수 비율</th><th>누수 / 표본</th></tr></thead>
          <tbody>{m.calibration.map((b) => (
            <tr key={b.bin}><td className="mono">{b.bin + 1}</td>
              <td><div className="flex items-center gap-2"><div className="flex-1"><Bar value={b.pred_mean / maxRate} gray /></div><span className="mono w-14 text-right text-[13px]">{(b.pred_mean * 100).toFixed(2)}%</span></div></td>
              <td><div className="flex items-center gap-2"><div className="flex-1"><Bar value={b.obs_rate / maxRate} /></div><span className="mono w-14 text-right text-[13px]">{(b.obs_rate * 100).toFixed(2)}%</span></div></td>
              <td className="mono text-[13px]">{b.leaks} / {b.n.toLocaleString()}</td></tr>
          ))}</tbody>
        </table></div>
      </Card>

      <Card className="mt-3" title="원인별 누수 건수와 유형" sub="건수 3건 이하는 해석하지 않습니다">
        <div className="overflow-x-auto"><table className="tbl">
          <thead><tr><th>원인</th><th style={{ width: "26%" }}>건수</th><th>모델 AUC</th><th>톤수 순 AUC</th><th>β (90% 범위)</th><th>유형</th></tr></thead>
          <tbody>{causes.map((c) => {
            const b = d.beta_by_cause.find((x) => x.cause === c.cause);
            return (
              <tr key={c.cause}><td>{label(c.cause)}</td>
                <td><div className="flex items-center gap-2"><div className="flex-1"><Bar value={c.n / maxN} /></div><b className="mono w-6 text-right">{c.n}</b></div></td>
                <td className={`mono ${c.n <= 3 ? "muted" : ""}`}>{num(c.auc_model)}</td><td className={`mono ${c.n <= 3 ? "muted" : ""}`}>{num(c.auc_tons_order)}</td>
                <td className="mono text-[13px]">{b ? `${b.beta.toFixed(2)} (${b.beta_lo.toFixed(2)}~${b.beta_hi.toFixed(2)})` : "—"}</td><td>{b?.type ?? "—"}</td></tr>
            );
          })}</tbody>
        </table></div>
      </Card>

      <p className="info-strip mt-3">기획서의 누수 예방률(교체 정책을 바꿔 다시 돌린 결과)은 아직 측정하지 않았습니다. 위 지표는 예측 순위의 구분 능력입니다.</p>
      <p className="muted mt-2 text-[12.5px]">{d.note}</p>
    </div>
  );
}
