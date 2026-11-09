import { useCallback, useEffect, useRef, useState } from "react";
import { api, backendOnline } from "./api";
import type { Handover, PlantConfig, ScenarioInfo, Series, State } from "./types";
import { StatusChip, fmtElapsed, fmtTime } from "./components/ui";
import MonitorView from "./views/MonitorView";
import DiagnosisView from "./views/DiagnosisView";
import InspectView from "./views/InspectView";
import HandoverView from "./views/HandoverView";
import MetricsView from "./views/MetricsView";
import ScenarioView from "./views/ScenarioView";
import AskPanel from "./components/AskPanel";
import PredictView from "./views/PredictView";
import PlanView from "./views/PlanView";
import RiskEvalView from "./views/RiskEvalView";
import AskView from "./views/AskView";
import SecurityView from "./views/SecurityView";
import { ROLES, type Role } from "./llmApi";

type Tab = "predict" | "plan" | "riskeval" | "ask" | "security" | "monitor" | "diagnosis" | "inspect" | "handover" | "metrics" | "scenario";
type Theme = "light" | "dark";
const TABS: { id: Tab; label: string }[] = [
  { id: "predict", label: "위험 예측" }, { id: "plan", label: "휴지 교체 계획" }, { id: "riskeval", label: "검증" }, { id: "ask", label: "질의응답" }, { id: "security", label: "AI 보안·감사" },
  { id: "monitor", label: "조기 감지" }, { id: "diagnosis", label: "진단" }, { id: "inspect", label: "점검" },
  { id: "handover", label: "인수인계" }, { id: "metrics", label: "비교·지표" }, { id: "scenario", label: "시나리오" },
];
const START_TS = 1500;
const THEME_KEY = "segnal-theme";     // 예전 키("theme")에는 이전 기본값 light가 저장돼 있어 다크 기본이 적용되지 않는다

function loadTheme(): Theme {
  try { const t = localStorage.getItem(THEME_KEY); if (t === "dark" || t === "light") return t; } catch { /* 저장소 사용 불가 */ }
  return "dark";
}

export default function App() {
  const [config, setConfig] = useState<PlantConfig | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [scenarioId, setScenarioId] = useState("leak_ramp_s5");
  const [ts, setTs] = useState(START_TS);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(30);
  const [state, setState] = useState<State | null>(null);
  const [series, setSeries] = useState<Series | null>(null);
  const [handover, setHandover] = useState<Handover | null>(null);
  const [polishing, setPolishing] = useState(false);
  const [tab, setTab] = useState<Tab>("predict");
  const [role, setRole] = useState<Role>("정비담당");
  const llmTab = tab === "predict" || tab === "plan" || tab === "riskeval" || tab === "ask" || tab === "security";
  const user = `${role}-01`;
  const [online, setOnline] = useState<boolean | null>(null);
  const [version, setVersion] = useState(0);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const reqId = useRef(0);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* 저장소 사용 불가 */ }
  }, [theme]);

  useEffect(() => {
    api.config().then(setConfig);
    api.scenarios().then(setScenarios);
  }, []);

  const nSamples = scenarios.find((s) => s.id === scenarioId)?.n_samples ?? 4320;

  const pick = useCallback(async (id: string, startTs = START_TS) => {
    setPlaying(false);
    await api.start(id);
    setScenarioId(id);
    setTs(startTs);
    setVersion((v) => v + 1);
  }, []);

  useEffect(() => {
    const id = ++reqId.current;
    api.state(scenarioId, ts).then((st) => {
      if (id !== reqId.current) return;
      setOnline(backendOnline);
      if (!backendOnline) { setState(null); return; }
      setState(st);
      const g = st.alert.group ?? 2;
      api.series(scenarioId, g, ts).then((se) => { if (id === reqId.current) setSeries(se); });
      if (tab === "handover") api.handover(scenarioId, ts).then((h) => { if (id === reqId.current) setHandover(h); });
    });
  }, [scenarioId, ts, version, tab]);

  // 백엔드가 아직 켜지는 중이면(시작 후 준비에 10초쯤 걸림) 3초마다 자동으로 다시 시도한다
  useEffect(() => {
    if (online !== false) return;
    const t = setInterval(() => {
      api.config().then(setConfig);
      api.scenarios().then(setScenarios);
      setVersion((v) => v + 1);
    }, 3000);
    return () => clearInterval(t);
  }, [online]);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setTs((v) => (v + speed >= nSamples - 1 ? (setPlaying(false), nSamples - 1) : v + speed)), 700);
    return () => clearInterval(t);
  }, [playing, speed, nSamples]);

  const onInspect = async (segment: number, result: "leak_confirmed" | "no_issue") => {
    await api.inspect(scenarioId, segment, result, ts);
    setVersion((v) => v + 1);
  };
  const onDelete = async (id: number) => {
    await api.deleteInspection(scenarioId, id);
    setVersion((v) => v + 1);
  };
  const onPolish = async () => {
    if (!handover) return;
    const id = reqId.current;
    setPolishing(true);
    const polished = await api.polishHandover(scenarioId, ts, handover);
    setPolishing(false);
    if (id === reqId.current) setHandover(polished);     // 기다리는 동안 시각이 바뀌었으면 옛 시각의 노트를 덮어쓰지 않는다
  };

  const header = (
    <header className="topbar">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-5 px-4">
        <h1 className="py-3 text-[16px] font-bold">세그널 · 연주기 냉각수 누수 예지보전</h1>
        <nav className="flex flex-wrap" aria-label="화면">
          {TABS.map((t) => (
            <button key={t.id} className="tab" aria-current={tab === t.id} onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </nav>
        <span className="ml-auto flex flex-wrap items-center gap-2 py-2">
          {state && !llmTab && <StatusChip level={state.alert.level} />}
          <label className="flex items-center gap-1.5 text-[12.5px]"><span className="muted">역할(데모)</span>
            <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="역할">{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</select>
          </label>
          <span className="chip chip-dash">합성 데이터</span>
          {!llmTab && <span className="muted text-[12.5px]">경과 {fmtElapsed(ts)}</span>}
          <span className="inline-flex overflow-hidden rounded-md border" style={{ borderColor: "var(--line)" }} role="group" aria-label="테마">
            {(["light", "dark"] as Theme[]).map((t) => (
              <button key={t} className="px-2.5 py-1 text-[12.5px]" aria-pressed={theme === t} onClick={() => setTheme(t)}
                style={{ background: theme === t ? "var(--primary)" : "var(--card)", color: theme === t ? "var(--primary-fg)" : "var(--text)", fontWeight: theme === t ? 700 : 400 }}>
                {t === "light" ? "밝게" : "어둡게"}
              </button>
            ))}
          </span>
        </span>
      </div>
    </header>
  );

  if (!config) return <div className="p-6">{header}불러오는 중…</div>;

  if (online === false) {
    return (
      <div>
        {header}
        <main className="mx-auto max-w-[1440px] p-4">
          <section className="card">
            <h3 className="card-title">백엔드에 연결되지 않았습니다</h3>
            <p className="mt-1 text-[14.5px]">백엔드(8000번)가 아직 켜지는 중이면 10초쯤 기다리세요. 3초마다 자동으로 다시 연결을 시도하며, 연결되면 이 안내가 사라집니다.</p>
            <p className="muted mt-1 text-[14px]">계속 이 화면이면 프로젝트 폴더의 run.bat을 실행해 백엔드 창이 열렸는지 확인하세요. 실제 계산 결과가 아닌 예시 화면을 시연으로 오해하지 않도록 예시 데이터는 보여 주지 않습니다.</p>
          </section>
        </main>
      </div>
    );
  }

  const sum = state?.summary;
  const bannerColor = state?.alert.level === "alarm" ? "var(--alarm)" : state?.alert.level === "watch" ? "var(--watch)" : "var(--line)";

  return (
    <div>
      {header}
      <main className="mx-auto max-w-[1440px] space-y-3 p-4">
        {tab !== "scenario" && !llmTab && (
          <section className="card flex flex-wrap items-center gap-3 !py-2 text-[13.5px]">
            <button className="btn btn-sm" onClick={() => setPlaying((p) => !p)}>{playing ? "❚❚ 일시정지" : "▶ 재생"}</button>
            <label className="flex items-center gap-1.5"><span className="muted">속도</span>
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                {[10, 30, 60, 120, 240].map((v) => <option key={v} value={v}>{v}분/틱</option>)}
              </select>
            </label>
            <input type="range" min={0} max={nSamples - 1} value={ts} onChange={(e) => setTs(Number(e.target.value))} className="min-w-[200px] flex-1" aria-label="시각" />
            <span>{fmtTime(ts)}</span>
            <span className="muted">{scenarios.find((s) => s.id === scenarioId)?.name}</span>
          </section>
        )}

        {state && sum && (tab === "monitor") && (
          <section className="card flex flex-wrap items-center gap-3" style={{ borderLeft: `5px solid ${bannerColor}` }}>
            <div className="min-w-[260px] flex-1">
              <div className="text-[18px] font-bold">{sum.headline}</div>
              <div className="muted mt-0.5 text-[14px]">{sum.detail}</div>
            </div>
            {sum.secondary_label && sum.secondary_tab && <button className="btn" onClick={() => setTab(sum.secondary_tab as Tab)}>{sum.secondary_label}</button>}
            {sum.primary_label && sum.primary_tab && <button className="btn btn-primary" onClick={() => setTab(sum.primary_tab as Tab)}>{sum.primary_label}</button>}
          </section>
        )}

        {tab === "predict" ? <PredictView role={role} user={user} onPlan={() => setTab("plan")} /> : tab === "plan" ? <PlanView role={role} user={user} /> : tab === "riskeval" ? <RiskEvalView /> : tab === "ask" ? <AskView role={role} user={user} /> : tab === "security" ? <SecurityView role={role} /> : tab === "metrics" ? <MetricsView state={state} series={series} ts={ts} /> : tab === "scenario" ? (
          <ScenarioView scenarios={scenarios} scenarioId={scenarioId} onPick={pick} onReset={() => pick(scenarioId)}
            playing={playing} onTogglePlay={() => setPlaying((p) => !p)} speed={speed} onSpeed={setSpeed} ts={ts} nSamples={nSamples} onSeek={setTs} />
        ) : !state || !series ? (
          <div className="p-6">불러오는 중…</div>
        ) : tab === "monitor" ? (
          <MonitorView config={config} state={state} series={series} ts={ts} />
        ) : tab === "diagnosis" ? (
          <DiagnosisView state={state} scenarioId={scenarioId} ts={ts} imbSeries={series} />
        ) : tab === "inspect" ? (
          <InspectView config={config} state={state} onInspect={onInspect} onDelete={onDelete} />
        ) : (
          <HandoverView handover={handover} polishing={polishing} onPolish={onPolish} />
        )}

        {!llmTab && <AskPanel scenarioId={scenarioId} ts={ts} onRecord={onInspect} />}

        <footer className="muted pt-2 text-[12.5px]">
          모든 데이터는 합성입니다. 경보 기준값은 현장 확인 전 가설이며, 이 화면은 점검 후보를 제시할 뿐 확정하지 않습니다.
        </footer>
      </main>
    </div>
  );
}
