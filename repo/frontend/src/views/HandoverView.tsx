import { Fragment, useEffect, useState } from "react";
import type { Handover } from "../types";
import { Card, PageHead } from "../components/ui";

const CHECKS = ["위치와 시각이 맞다", "점검 결과가 맞다", "다음 할 일이 적합하다"];

/** 계산에서 그대로 옮긴 값은 파란 바탕으로 칠한다 */
function highlight(text: string, values: string[]) {
  const vs = values.filter(Boolean).map((v) => v.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!vs.length) return text;
  const parts = text.split(new RegExp(`(${vs.join("|")})`, "g"));
  return parts.map((p, i) => (values.includes(p) ? <span key={i} className="calc">{p}</span> : <Fragment key={i}>{p}</Fragment>));
}

export default function HandoverView({ handover }: { handover: Handover | null }) {
  const [checked, setChecked] = useState<boolean[]>([false, false, false]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState<"" | "copy" | "confirm">("");
  useEffect(() => { setChecked([false, false, false]); setEditing(false); setDraft(handover?.text ?? ""); setCopied(""); }, [handover?.text]);

  if (!handover) return <div><PageHead title="인수인계 노트" /><Card><p className="muted">불러오는 중…</p></Card></div>;
  const all = checked.every(Boolean);
  const body = editing ? draft : handover.text;
  const copy = async (kind: "copy" | "confirm") => {
    try { await navigator.clipboard.writeText(body); setCopied(kind); } catch { /* 클립보드를 쓸 수 없는 환경 */ }
  };

  return (
    <div>
      <PageHead title="인수인계 노트" sub="확인한 뒤에만 전달합니다. 자동으로 보내지 않습니다. 읽어 보고 맞으면 다음 교대에 전달합니다." />
      <div className="grid gap-3 lg:grid-cols-[1fr_340px]">
        <Card>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-[17px] font-bold">{handover.title || "인수인계 노트 (초안)"}</h3>
            <span className="flex items-center gap-2">
              <span className="muted text-[12.5px]">{handover.generated_by === "llm" ? "문장은 LLM이 다듬음" : "정해진 양식으로 작성"}</span>
              <span className={`chip ${copied ? "chip-ok" : ""}`}>{copied === "confirm" ? "확인 후 복사함" : copied === "copy" ? "복사함" : "전달 전"}</span>
            </span>
          </div>

          {!handover.ready && (
            <p className="info-strip mb-3 text-[14px]">
              아직 노트를 완성할 수 없습니다. 누수가 점검으로 확인되면 완성됩니다.{handover.missing.length > 0 && <> 빠진 내용: {handover.missing.join(", ")}.</>}
            </p>
          )}

          {editing ? (
            <textarea className="w-full text-[14.5px]" rows={9} value={draft} onChange={(e) => setDraft(e.target.value)} />
          ) : (
            <div>
              {handover.sections.map((s) => (
                <div key={s.title} className="grid grid-cols-[84px_1fr] gap-3 border-t py-2.5 text-[14.5px]" style={{ borderColor: "var(--line)" }}>
                  <b className="muted font-semibold">{s.title}</b>
                  <p>{highlight(s.text, s.values.map((v) => v.value))}</p>
                </div>
              ))}
            </div>
          )}

          <p className="muted mt-2 flex items-center gap-2 text-[12.5px]"><span className="calc">파란 바탕</span>은 계산에서 그대로 옮긴 값입니다.</p>
          <div className="mt-4 flex flex-wrap gap-2 border-t pt-3" style={{ borderColor: "var(--line)" }}>
            <button className="btn btn-primary" disabled={!all || !handover.ready} onClick={() => copy("confirm")}>확인하고 복사</button>
            <button className="btn" onClick={() => setEditing((e) => !e)}>{editing ? "고치기 끝" : "고치기"}</button>
            <button className="btn" onClick={() => copy("copy")}>복사</button>
            {copied && <span className="ml-1 self-center text-[13px]" style={{ color: "var(--ok)" }}>클립보드에 복사했습니다. 전달은 사람이 직접 합니다.</span>}
          </div>
        </Card>

        <div className="space-y-3">
          <Card title="보내기 전에 확인">
            <ul className="space-y-2.5">
              {CHECKS.map((c, i) => (
                <li key={c}>
                  <label className="flex cursor-pointer items-center gap-2.5 text-[14.5px]">
                    <input type="checkbox" className="h-4 w-4" checked={checked[i]} onChange={() => setChecked((o) => o.map((v, j) => (j === i ? !v : v)))} />
                    {c}
                  </label>
                </li>
              ))}
            </ul>
            {!handover.ready && <p className="muted mt-2 text-[12.5px]">누수 확인 전에는 '확인하고 복사'가 닫혀 있습니다.</p>}
          </Card>
          <Card title="노트의 값" sub="어디서 계산했나">
            {handover.sources.length === 0 ? <p className="muted text-[13.5px]">표시할 값이 없습니다.</p> : (
              <dl className="space-y-2.5 text-[13.5px]">
                {handover.sources.map((v) => (
                  <div key={v.label}>
                    <dt className="flex items-baseline justify-between gap-2"><b>{v.label}</b><span className="calc text-[12.5px]">{v.value}</span></dt>
                    <dd className="muted text-[12.5px]">{v.source}</dd>
                  </div>
                ))}
              </dl>
            )}
          </Card>
          <Card title="이 노트를 만든 방법">
            <p className="text-[13.5px]">문장은 정해진 양식(또는 언어 모델)이 만들었고, 숫자는 계산 결과를 그대로 옮겼습니다.</p>
            <p className="muted mt-2 text-[13.5px]">문장에 틀린 내용이 있을 수 있습니다. 사람이 읽고 확인한 뒤 전달합니다. 합성 데이터로 만든 시연입니다.</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
