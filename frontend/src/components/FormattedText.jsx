// Renders the agent's plain-text answers: paragraphs, "-" / "1." lists and **bold**, without innerHTML.
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4
      ? <strong key={i}>{part.slice(2, -2)}</strong>
      : part,
  );
}

export default function FormattedText({ text }) {
  const blocks = [];
  let list = null;
  for (const raw of String(text || "").split(/\r?\n/)) {
    const line = raw.trimEnd();
    const item = line.match(/^\s*(?:([-•*])|(\d+)[.)])\s+(.*)$/);
    if (item) {
      const ordered = Boolean(item[2]);
      if (!list || list.ordered !== ordered) {
        list = { ordered, start: ordered ? Number(item[2]) : undefined, items: [] };
        blocks.push(list);
      }
      list.items.push(item[3]);
      continue;
    }
    list = null;
    if (!line.trim()) continue;
    const isLabel = line.trim().endsWith(":") && line.length < 70;
    blocks.push({ text: line.trim(), isLabel });
  }

  return (
    <div className="formatted">
      {blocks.map((b, i) => {
        if (b.items) {
          const Tag = b.ordered ? "ol" : "ul";
          return (
            <Tag key={i} start={b.start}>
              {b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}
            </Tag>
          );
        }
        return b.isLabel ? <p key={i} className="label-line"><strong>{inline(b.text)}</strong></p> : <p key={i}>{inline(b.text)}</p>;
      })}
    </div>
  );
}
