import type { ReactNode } from "react";
// Deliberately small Markdown subset. React escapes all text; no raw HTML,
// links, image fetches, eval, innerHTML, remote syntax highlighter or scripts.
function inline(text: string): ReactNode[] {
  return text
    .split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g)
    .map((part, i) =>
      part.startsWith("`") && part.endsWith("`") ? (
        <code key={i}>{part.slice(1, -1)}</code>
      ) : part.startsWith("**") && part.endsWith("**") ? (
        <strong key={i}>{part.slice(2, -2)}</strong>
      ) : (
        part
      ),
    );
}
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let code: string[] | null = null;
  let language = "";
  const lines = text.slice(0, 65536).split("\n");
  for (const [i, line] of lines.entries()) {
    if (line.startsWith("```")) {
      if (code) {
        blocks.push(
          <pre key={i} aria-label={language ? `代码 ${language}` : "代码"}>
            <code>{code.join("\n")}</code>
          </pre>,
        );
        code = null;
      } else {
        code = [];
        language = line.slice(3).trim().slice(0, 40);
      }
    } else if (code) code.push(line);
    else if (/^#{1,3} /.test(line))
      blocks.push(<h3 key={i}>{inline(line.replace(/^#{1,3} /, ""))}</h3>);
    else if (/^[-*] /.test(line))
      blocks.push(
        <p className="markdown-bullet" key={i}>
          • {inline(line.slice(2))}
        </p>,
      );
    else if (line.trim()) blocks.push(<p key={i}>{inline(line)}</p>);
  }
  if (code)
    blocks.push(
      <pre key="unfinished">
        <code>{code.join("\n")}</code>
      </pre>,
    );
  return <div className="ai-markdown">{blocks}</div>;
}
