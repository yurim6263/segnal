import type { ReactNode } from "react";

/** 답변 형식("## 소제목", "- 항목", 그 밖은 문단)을 소제목·목록으로 그린다. 형식이 아니면 문단으로 보인다. */
type Block = { kind: "h"; text: string } | { kind: "li"; text: string } | { kind: "p"; text: string };

function parse(text: string): Block[] {
  const out: Block[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    if (/^#{1,3}\s+/.test(line)) out.push({ kind: "h", text: line.replace(/^#{1,3}\s+/, "") });
    else if (/^[-•·*]\s+/.test(line)) out.push({ kind: "li", text: line.replace(/^[-•·*]\s+/, "") });
    else if (/^\d+[.)]\s+/.test(line)) out.push({ kind: "li", text: line.replace(/^\d+[.)]\s+/, "") });
    else out.push({ kind: "p", text: line });
  }
  return out;
}

const inline = (t: string): ReactNode[] => t.split(/(\*\*[^*]+\*\*)/g).map((s, i) => (s.startsWith("**") && s.endsWith("**") ? <b key={i}>{s.slice(2, -2)}</b> : <span key={i}>{s}</span>));

const ICON: Record<string, string> = { 결론: "◆", 근거: "▸", "두 경우": "⇄", 가정: "※", "확인할 점": "?", "다음 할 일": "→", 후보: "▸" };

export default function AnswerText({ text }: { text: string }) {
  const blocks = parse(text);
  const out: ReactNode[] = [];
  let items: string[] = [];
  const flush = (key: number) => {
    if (items.length) {
      out.push(<ul key={`u${key}`} className="mt-1 space-y-1">{items.map((t, i) => (
        <li key={i} className="grid grid-cols-[14px_1fr] gap-1 text-[13.5px] leading-[1.55]"><span className="muted" aria-hidden>•</span><span>{inline(t)}</span></li>
      ))}</ul>);
      items = [];
    }
  };
  blocks.forEach((b, i) => {
    if (b.kind === "li") { items.push(b.text); return; }
    flush(i);
    if (b.kind === "h") {
      out.push(
        <div key={i} className="mt-2.5 flex items-center gap-1.5 border-b pb-0.5 text-[12.5px] font-bold first:mt-0" style={{ borderColor: "var(--line)", color: b.text === "결론" ? "var(--primary)" : "var(--muted)" }}>
          <span aria-hidden>{ICON[b.text] ?? "▸"}</span>{b.text}
        </div>,
      );
    } else {
      const lead = out.length > 0 && blocks[i - 1]?.kind === "h" && (blocks[i - 1] as { text: string }).text === "결론";
      out.push(<p key={i} className={lead ? "mt-1 text-[15px] font-semibold leading-snug" : "mt-1 text-[13.5px] leading-[1.55]"}>{inline(b.text)}</p>);
    }
  });
  flush(blocks.length);
  return <div>{out}</div>;
}
