import type { State } from "../types";
import { fmtTime } from "./ui";

/** 조기 감지를 화면 맨 위에서 보이는 띠: 추세 감지 경보 시각과 고정 임계값 경보 시각의 차이 */
export default function EarlyStrip({ state }: { state: State }) {
  const d = state.alert.detectors;
  const ew = d.ewma_alarm_ts, fx = d.fixed_alarm_ts;
  if (state.alert.level === "normal" && ew == null) return null;
  return (
    <div className="mb-3 grid gap-2 rounded-lg border p-3 md:grid-cols-[1.1fr_1fr_1fr]" style={{ borderColor: "var(--line)", background: "var(--card)" }}>
      <div>
        <p className="muted text-[12px]">조기 감지</p>
        {ew != null && fx != null
          ? <p className="text-[18px] font-bold">고정 임계값보다 <span style={{ color: "var(--primary)" }}>{fx - ew}분</span> 먼저 알았습니다</p>
          : ew != null
            ? <p className="text-[18px] font-bold">고정 임계값은 <span style={{ color: "var(--primary)" }}>아직 울리지 않았는데</span> 먼저 알았습니다</p>
            : <p className="text-[16px] font-bold">원인을 확인하는 중입니다</p>}
        <p className="muted mt-0.5 text-[12px]">이미 새기 시작한 작은 누수를 커지기 전에 찾습니다(합성 데이터 기준).</p>
      </div>
      <div><p className="muted text-[12px]">추세 감지 경보 (우리 방식)</p><p className="text-[15.5px] font-semibold">{ew != null ? fmtTime(ew) : "—"}</p></div>
      <div><p className="muted text-[12px]">고정 임계값 경보 (기존 방식)</p><p className="text-[15.5px] font-semibold">{fx != null ? fmtTime(fx) : "아직 없음"}</p></div>
    </div>
  );
}
