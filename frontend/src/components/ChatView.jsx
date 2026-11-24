import { useEffect, useRef, useState } from "react";
import { formatDateTime, toolLabel } from "../lib/format.js";
import FormattedText from "./FormattedText.jsx";
import ToolTrace from "./ToolTrace.jsx";
import { IconBolt, IconCheck, IconGauge, IconScan, IconSend, IconTool, IconX, Spinner } from "./icons.jsx";
import { LogoMark } from "./Logo.jsx";

const SUGGESTIONS = [
  { tag: "Now", icon: <IconGauge width={18} height={18} />, text: "What needs attention first right now, who is on it, and what should they do?" },
  { tag: "Who", icon: <IconScan width={18} height={18} />, text: "Who is on shift for the Gas Station, and what is open there?" },
  { tag: "Usage", icon: <IconBolt width={18} height={18} />, text: "Is compressed air usage normal today?" },
  { tag: "Patterns", icon: <IconTool width={18} height={18} />, text: "Which equipment keeps having problems, and how quickly do we respond?" },
];

function Progress({ progress }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);
  const elapsed = Math.max(0, Math.round((now - progress.startedAt) / 1000));
  return (
    <div className="msg bot" aria-live="polite">
      <span className="bot-avatar"><LogoMark size={16} /></span>
      <div className="bubble bot-bubble progress">
        <div className="progress-head"><Spinner /> Working on it… <span className="muted">{elapsed}s</span></div>
        {progress.steps.length > 0 && (
          <ul className="progress-steps">
            {progress.steps.map((s) => (
              <li key={s.step} className={s.status}>
                {s.status === "running" ? <Spinner size={12} /> : s.status === "done"
                  ? <IconCheck width={14} height={14} /> : <IconX width={14} height={14} />}
                {toolLabel(s.tool)}
              </li>
            ))}
          </ul>
        )}
        {progress.thinking && <div className="progress-thinking muted">{progress.steps.length ? "Reviewing the results…" : "Planning which data to check…"}</div>}
      </div>
    </div>
  );
}

function Message({ m }) {
  if (m.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble user-bubble">{m.content}</div>
      </div>
    );
  }
  return (
    <div className="msg bot">
      <span className="bot-avatar"><LogoMark size={16} /></span>
      <div className={`bubble bot-bubble${m.is_error ? " error" : ""}`}>
        <FormattedText text={m.content} />
        <div className="bubble-foot">
          <span className="muted">{formatDateTime(m.created_at)}</span>
          {!m.is_error && <ToolTrace message={m} />}
        </div>
      </div>
    </div>
  );
}

export default function ChatView({ messages, busy, progress, error, loading, onSend, userName, hasData = true, onOpenData }) {
  const [text, setText] = useState("");
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, progress]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  async function submit(value = text) {
    const msg = value.trim();
    if (!msg || busy) return;
    setText("");
    const ok = await onSend(msg);
    if (ok === false) setText(msg); // restore on failure
    inputRef.current?.focus();
  }

  const empty = !loading && messages.length === 0;
  return (
    <section className="chat">
      <div className="messages">
        {loading && <div className="center muted"><Spinner /> Loading conversation…</div>}
        {empty && (
          <div className="chat-empty">
            <span className="hero-mark"><LogoMark size={30} /></span>
            <h2>Hi {userName?.split(" ")[0] || "there"}, what should we check?</h2>
            <p className="muted">
              I watch the utilities behind the iPhone line (compressed air, water, HVAC, nitrogen) using the data you uploaded: consumption trends, abnormal usage,
              links to downtime, and simple ways to save. I advise - certified operators stay in
              control of the plant.
            </p>
            {!hasData && (
              <div className="banner" role="status">
                No data uploaded yet, so I have nothing to analyse.
                <button className="btn primary xs" onClick={onOpenData}>Upload data</button>
              </div>
            )}
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s.tag} className="suggestion" onClick={() => submit(s.text)} disabled={busy}>
                  <span className="sug-icon" aria-hidden="true">{s.icon}</span>
                  <span className="sug-body"><span className="sug-tag">{s.tag}</span><span className="sug-text">{s.text}</span></span>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => <Message key={m.id} m={m} />)}
        {progress && <Progress progress={progress} />}
        {error && <div className="chat-error" role="alert">{error}</div>}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <textarea
          ref={inputRef}
          rows={1}
          value={text}
          maxLength={4000}
          placeholder="Ask about leaks, pressure, chillers, downtime, maintenance…"
          aria-label="Message the utilities agent"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button className="btn primary send" disabled={busy || !text.trim()} aria-label="Send message">
          {busy ? <Spinner /> : <IconSend width={16} height={16} />}
        </button>
      </form>
      <p className="composer-hint">Enter to send · Shift+Enter for a new line · Answers use live plant data and site-engineered limits.</p>
    </section>
  );
}
