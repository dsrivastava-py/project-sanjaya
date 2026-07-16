// Tiny markdown renderer for journal text — headings, bold, italic, inline
// code, links, lists, paragraphs. Builds React nodes (no innerHTML → XSS-safe)
// and keeps ~30KB of react-markdown out of the bundle (§12 budget).
import type { ReactNode } from "react";

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  // tokens: **bold**, *italic*, `code`, [label](url)
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`"))
      out.push(
        <code key={key} className="rounded bg-surface2 px-1 py-0.5 text-[13px]">
          {tok.slice(1, -1)}
        </code>,
      );
    else if (tok.startsWith("[")) {
      const mm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok);
      if (mm)
        out.push(
          <a key={key} href={mm[2]} target="_blank" rel="noreferrer" className="text-accent underline">
            {mm[1]}
          </a>,
        );
      else out.push(tok);
    } else out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split(/\r?\n/);
  let list: string[] = [];
  let para: string[] = [];
  let key = 0;

  const flushList = () => {
    if (!list.length) return;
    blocks.push(
      <ul key={`ul${key++}`} className="my-2 list-disc space-y-1 pl-5">
        {list.map((it, i) => (
          <li key={i}>{inline(it, `li${key}-${i}`)}</li>
        ))}
      </ul>,
    );
    list = [];
  };
  const flushPara = () => {
    if (!para.length) return;
    blocks.push(
      <p key={`p${key++}`} className="my-2 leading-relaxed">
        {inline(para.join(" "), `p${key}`)}
      </p>,
    );
    para = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    const li = /^[-*]\s+(.*)$/.exec(line);
    if (!line.trim()) {
      flushList();
      flushPara();
    } else if (h) {
      flushList();
      flushPara();
      const level = h[1].length;
      const cls =
        level === 1
          ? "mt-3 mb-1 font-display text-[18px] font-semibold"
          : "mt-3 mb-1 font-display text-[15px] font-semibold";
      blocks.push(
        <div key={`h${key++}`} className={cls}>
          {inline(h[2], `h${key}`)}
        </div>,
      );
    } else if (li) {
      flushPara();
      list.push(li[1]);
    } else {
      flushList();
      para.push(line);
    }
  }
  flushList();
  flushPara();
  return <div className="text-[15px] text-ink1">{blocks}</div>;
}
