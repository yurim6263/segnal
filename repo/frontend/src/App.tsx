import { useEffect, useState } from "react";
import PredictView from "./views/PredictView";
import PlanView from "./views/PlanView";
import WorkOrderView from "./views/WorkOrderView";
import AskPanel from "./components/AskPanel";
import { llm, ROLES, type ApiError, type Role } from "./llmApi";

type Tab = "predict" | "plan" | "workorders";
type Theme = "light" | "dark";
const TABS: { id: Tab; label: string }[] = [
  { id: "predict", label: "위험 예측" }, { id: "plan", label: "휴지 교체 계획" }, { id: "workorders", label: "작업지시서" },
];
const THEME_KEY = "segnal-theme";     // 예전 키("theme")에는 이전 기본값 light가 저장돼 있어 다크 기본이 적용되지 않는다
const FONT_KEY = "segnal-font";
const FONT_SIZES = [{ id: "normal", label: "보통" }, { id: "large", label: "크게" }, { id: "xlarge", label: "더 크게" }] as const;   // 배율은 index.css의 data-font
type FontSize = (typeof FONT_SIZES)[number]["id"];

function loadFont(): FontSize {
  try { const f = localStorage.getItem(FONT_KEY); if (FONT_SIZES.some((x) => x.id === f)) return f as FontSize; } catch { /* 저장소 사용 불가 */ }
  return "normal";
}

function loadTheme(): Theme {
  try { const t = localStorage.getItem(THEME_KEY); if (t === "dark" || t === "light") return t; } catch { /* 저장소 사용 불가 */ }
  return "dark";
}

export default function App() {
  const [tab, setTab] = useState<Tab>("predict");
  const [role, setRole] = useState<Role>("정비담당");
  const user = `${role}-01`;
  const [online, setOnline] = useState<boolean | null>(null);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [fontSize, setFontSize] = useState<FontSize>(loadFont);
  const [openWo, setOpenWo] = useState<string | null>(null);     // 다른 탭에서 만들거나 누른 작업지시서를 작업지시서 탭에서 연다
  const openWorkOrder = (id: string) => { setOpenWo(id); setTab("workorders"); };

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* 저장소 사용 불가 */ }
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute("data-font", fontSize);
    try { localStorage.setItem(FONT_KEY, fontSize); } catch { /* 저장소 사용 불가 */ }
  }, [fontSize]);

  // 백엔드가 아직 켜지는 중이면 3초마다 자동으로 다시 시도한다. 연결 실패(status 0)만 꺼진 것으로 본다
  useEffect(() => {
    if (online) return;
    let active = true;
    const probe = () => llm.roles()
      .then(() => { if (active) setOnline(true); })
      .catch((e: ApiError) => { if (active) setOnline(e.status !== 0); });
    probe();
    const t = setInterval(probe, 3000);
    return () => { active = false; clearInterval(t); };
  }, [online]);

  const header = (
    <header className="topbar">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-5 px-4">
        <h1 className="flex items-center gap-1.5 py-2 text-[27px] font-extrabold tracking-tight" style={{ color: "var(--primary)" }}>
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M2 12h4l3-7 5 14 3-7h5" />
          </svg>
          Segnal
        </h1>
        <nav className="flex flex-wrap" aria-label="화면">
          {TABS.map((t) => (
            <button key={t.id} className="tab" aria-current={tab === t.id} onClick={() => { setOpenWo(null); setTab(t.id); }}>{t.label}</button>
          ))}
        </nav>
        <span className="ml-auto flex flex-wrap items-center gap-2 py-2">
          <label className="flex items-center gap-1.5 text-[12.5px]"><span className="muted">역할(데모)</span>
            <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="역할">{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</select>
          </label>
          <span className="chip chip-dash">합성 데이터</span>
          <span className="muted text-[12.5px]">글씨</span>
          <span className="inline-flex overflow-hidden rounded-md border" style={{ borderColor: "var(--line)" }} role="group" aria-label="글씨 크기">
            {FONT_SIZES.map((f) => (
              <button key={f.id} className="px-2.5 py-1 text-[12.5px]" aria-pressed={fontSize === f.id} onClick={() => setFontSize(f.id)}
                style={{ background: fontSize === f.id ? "var(--primary)" : "var(--card)", color: fontSize === f.id ? "var(--primary-fg)" : "var(--text)", fontWeight: fontSize === f.id ? 700 : 400 }}>
                {f.label}
              </button>
            ))}
          </span>
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

  if (online === null) return <div>{header}<p className="p-6">불러오는 중…</p></div>;

  if (online === false) {
    return (
      <div>
        {header}
        <main className="mx-auto max-w-[1440px] p-4">
          <section className="card">
            <h3 className="card-title">백엔드에 연결되지 않았습니다</h3>
            <p className="mt-1 text-[14.5px]">백엔드(8000번)가 아직 켜지는 중이면 10초쯤 기다리세요. 3초마다 자동으로 다시 연결을 시도하며, 연결되면 이 안내가 사라집니다.</p>
            <p className="muted mt-1 text-[14px]">계속 이 화면이면 프로젝트 폴더의 run.bat을 실행해 백엔드 창이 열렸는지 확인하세요.</p>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div>
      {header}
      <main className="mx-auto max-w-[1440px] space-y-3 p-4">
        {tab === "predict" ? <PredictView role={role} user={user} onPlan={() => setTab("plan")} onOpenWo={openWorkOrder} />
          : tab === "plan" ? <PlanView role={role} user={user} onOpenWo={openWorkOrder} />
          : <WorkOrderView role={role} user={user} openWoId={openWo} />}
        <AskPanel role={role} user={user} />

        <footer className="muted pt-2 text-[12.5px]">
          모든 데이터는 합성입니다. 예측값과 작업지시서는 판단을 돕는 초안이며, 최종 판단과 승인은 담당자가 합니다.
        </footer>
      </main>
    </div>
  );
}
