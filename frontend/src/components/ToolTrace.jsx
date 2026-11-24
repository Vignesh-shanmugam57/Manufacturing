import { compact, seconds, toolLabel } from "../lib/format.js";
import { IconCheck, IconTool, IconX } from "./icons.jsx";

export default function ToolTrace({ message }) {
  const steps = message.steps || [];
  const tokens = (message.input_tokens || 0) + (message.output_tokens || 0);
  const meta = [
    steps.length ? `${steps.length} tool call${steps.length === 1 ? "" : "s"}` : "no tools",
    message.duration_ms != null && seconds(message.duration_ms),
    message.llm_calls && `${message.llm_calls} model call${message.llm_calls === 1 ? "" : "s"}`,
    tokens > 0 && `${compact(tokens)} tokens`,
  ].filter(Boolean).join(" · ");

  if (!steps.length) return <div className="trace-meta">{meta}</div>;
  return (
    <details className="trace">
      <summary><IconTool width={14} height={14} /> {meta}</summary>
      <ol className="trace-steps">
        {steps.map((s, i) => (
          <li key={i} className={s.ok === false ? "failed" : ""}>
            <div className="trace-head">
              {s.ok === false ? <IconX width={14} height={14} /> : <IconCheck width={14} height={14} />}
              <span>{toolLabel(s.tool)}</span>
              <code>{s.tool}({s.input && Object.keys(s.input).length ? JSON.stringify(s.input) : ""})</code>
            </div>
            <pre>{s.output}</pre>
          </li>
        ))}
      </ol>
    </details>
  );
}
