import type { ScenarioInfo } from "../types";
import { Card, PageHead, fmtTime } from "../components/ui";

interface Props {
  scenarios: ScenarioInfo[];
  scenarioId: string;
  onPick: (id: string, startTs?: number) => void;
  onReset: () => void;
  playing: boolean;
  onTogglePlay: () => void;
  speed: number;
  onSpeed: (v: number) => void;
  ts: number;
  nSamples: number;
  onSeek: (v: number) => void;
}

const DEMOS = [
  { id: "normal_opchange", no: "시연 1", title: "주조 속도 변경", note: "정상 가동 중에 운전 조건만 바뀝니다. 오경보가 나지 않는지 봅니다." },
  { id: "leak_ramp_s5", no: "시연 2", title: "서서히 커지는 누수", note: "세그먼트 한 곳에서 조금씩 새기 시작합니다. 얼마나 일찍 알아차리는지 봅니다." },
];
const EVENTS: { id: string; label: string }[] = [
  { id: "leak_ramp_s5", label: "서서히 커지는 누수" }, { id: "leak_abrupt_s2", label: "급한 누수" }, { id: "clog_s7", label: "막힘" },
  { id: "pump_degrade", label: "펌프 저하" }, { id: "sensor_fault", label: "센서 고장" }, { id: "normal_opchange", label: "운전 조건 변경" },
  { id: "leak_small_s9", label: "아주 작은 누수" }, { id: "flow_offset_s5", label: "유량계 오차 (누수 아님)" }, { id: "leak_small_s1", label: "누수인지 구분 불가" },
];

export default function ScenarioView({ scenarios, scenarioId, onPick, onReset, playing, onTogglePlay, speed, onSpeed, ts, nSamples, onSeek }: Props) {
  const cur = scenarios.find((s) => s.id === scenarioId);
  const evLabel = EVENTS.find((e) => e.id === scenarioId)?.label ?? cur?.name ?? "";
  return (
    <div>
      <PageHead title="시나리오" sub="시뮬레이터에 넣을 이벤트를 고르고 재생합니다. 발표자가 쓰는 화면입니다." />
      <div className="grid gap-3 lg:grid-cols-[1fr_380px]">
        <div className="min-w-0 space-y-3">
          <Card title="준비한 시나리오" sub="시연 순서대로">
            <div className="grid gap-3 md:grid-cols-2">
              {DEMOS.map((d) => {
                const on = scenarioId === d.id;
                return (
                  <button key={d.id} className="rounded-lg border p-3 text-left" onClick={() => onPick(d.id, 1500)}
                    style={{ borderColor: on ? "var(--primary)" : "var(--line)", background: on ? "var(--info-bg)" : "var(--card)", borderWidth: on ? 2 : 1 }}>
                    <div className="card-sub" style={{ color: on ? "var(--primary)" : undefined }}>{d.no}{on ? ", 선택됨" : ""}</div>
                    <div className="mt-0.5 text-[17px] font-bold">{d.title}</div>
                    <div className="muted mt-1 text-[13px]">{d.note}</div>
                  </button>
                );
              })}
            </div>
          </Card>

          <Card title="이벤트 고르기" sub="준비된 시나리오 중에서 선택">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {EVENTS.map((e) => (
                <label key={e.id} className="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-[14px]"
                  style={{ borderColor: scenarioId === e.id ? "var(--primary)" : "var(--line)", background: scenarioId === e.id ? "var(--info-bg)" : "var(--card)" }}>
                  <input type="radio" name="event" checked={scenarioId === e.id} onChange={() => onPick(e.id, 1500)} />
                  {e.label}
                </label>
              ))}
            </div>
            <p className="muted mt-2 text-[12.5px]">누수 위치·시작 시각·크기를 직접 바꾸는 기능은 아직 없습니다. 준비된 시나리오만 고를 수 있습니다.</p>
          </Card>

          <Card title="전체 시나리오">
            <table className="tbl">
              <tbody>
                {scenarios.map((s) => (
                  <tr key={s.id}>
                    <td><b>{s.name}</b><div className="muted text-[12.5px]">{s.description}</div></td>
                    <td style={{ width: 80 }}><button className="btn btn-sm" onClick={() => onPick(s.id)}>{s.id === scenarioId ? "선택됨" : "열기"}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <div className="space-y-3">
          <Card>
            <div className="flex gap-2">
              <button className="btn btn-primary flex-1" onClick={onTogglePlay}>{playing ? "❚❚ 일시정지" : "▶ 재생"}</button>
              <button className="btn" onClick={onReset}>처음으로</button>
            </div>
            <label className="mt-3 block text-[13px]"><span className="card-sub">재생 속도</span>
              <select className="mt-1 w-full" value={speed} onChange={(e) => onSpeed(Number(e.target.value))}>
                <option value={10}>느리게 (10분/틱)</option><option value={30}>보통 (30분/틱)</option>
                <option value={60}>빠르게 (60분/틱)</option><option value={120}>아주 빠르게 (120분/틱)</option>
              </select>
            </label>
            <div className="mt-3">
              <input type="range" min={0} max={nSamples - 1} value={ts} onChange={(e) => onSeek(Number(e.target.value))} className="w-full" aria-label="시각" />
              <div className="muted flex justify-between text-[12px]"><span>시작</span><span>{fmtTime(ts)}</span><span>끝</span></div>
            </div>
            <p className="muted mt-2 text-[12.5px]">'처음으로'는 점검 기록을 지우고 시연을 처음 상태로 되돌립니다.</p>
          </Card>
          <Card title="이 화면에만 보입니다" sub="발표자용">
            <dl className="grid grid-cols-[70px_1fr] gap-y-2 text-[14px]">
              <dt className="muted">이벤트</dt><dd><b>{evLabel}</b></dd>
              <dt className="muted">설명</dt><dd>{cur?.description ?? "—"}</dd>
              <dt className="muted">길이</dt><dd>{cur ? `${(cur.n_samples / 1440).toFixed(0)}일` : "—"}</dd>
            </dl>
            <p className="muted mt-2 text-[12.5px]">감시, 진단, 점검 화면은 이벤트 정답을 모르고 측정값만으로 계산합니다. 이 화면의 설명은 발표자가 흐름을 잡기 위한 것입니다.</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
