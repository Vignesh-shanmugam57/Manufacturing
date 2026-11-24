import { useEffect, useState } from "react";
import { initials, timeAgo } from "../lib/format.js";
import { Logo } from "./Logo.jsx";
import { IconBell, IconCheck, IconChevron, IconCube, IconEdit, IconFlow, IconGauge, IconGrid, IconLogout, IconPlug, IconPlus, IconTrash, IconX } from "./icons.jsx";
import "../styles/menu.css";
import { useTwinResource } from "../lib/twin.js";

function SessionItem({ session, active, disabled, onOpen, onRename, onDelete }) {
  const [mode, setMode] = useState("view"); // view | edit | confirm
  const [title, setTitle] = useState(session.title);

  if (mode === "edit") {
    return (
      <form className="session-item editing" onSubmit={(e) => {
        e.preventDefault();
        if (title.trim()) onRename(session.id, title.trim());
        setMode("view");
      }}>
        <input autoFocus value={title} maxLength={200} aria-label="Chat title"
               onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setMode("view")} />
        <button className="icon-btn sm" aria-label="Save title"><IconCheck width={15} height={15} /></button>
      </form>
    );
  }
  if (mode === "confirm") {
    return (
      <div className="session-item confirm">
        <span>Delete this chat?</span>
        <button className="btn danger xs" onClick={() => onDelete(session.id)}>Delete</button>
        <button className="icon-btn sm" aria-label="Cancel" onClick={() => setMode("view")}><IconX width={15} height={15} /></button>
      </div>
    );
  }
  return (
    <div className={`session-item${active ? " active" : ""}${disabled ? " disabled" : ""}`}>
      <button className="session-open" onClick={() => onOpen(session.id)} disabled={disabled} title={session.title}>
        <span className="session-title">{session.title}</span>
        <span className="session-meta">
          {timeAgo(session.updated_at)} · {session.message_count} {session.message_count === 1 ? "msg" : "msgs"}
        </span>
      </button>
      <div className="session-actions">
        <button className="icon-btn sm" aria-label="Rename chat" onClick={() => { setTitle(session.title); setMode("edit"); }}>
          <IconEdit width={14} height={14} />
        </button>
        <button className="icon-btn sm" aria-label="Delete chat" onClick={() => setMode("confirm")} disabled={disabled}>
          <IconTrash width={14} height={14} />
        </button>
      </div>
    </div>
  );
}

/** What the plant team uses every day. */
const PLANT = [
  { id: "issues", label: "Issues", icon: <IconBell />, badgeKey: "attention" },
  { id: "map", label: "Plant map", icon: <IconCube /> },
  { id: "monitor", label: "Plant overview", icon: <IconGauge /> },
];

/** Setup and background: not needed day to day, so they live in a collapsible group. */
const MORE = [
  { id: "connectors", label: "Data connectors", icon: <IconPlug /> },
  { id: "flow", label: "Agent activity", icon: <IconFlow /> },
  { id: "architecture", label: "How it works", icon: <IconGrid /> },
];

export default function Sidebar({
  user, view, onView, sessions, activeId, busy, onNewChat, onOpen, onRename, onDelete, onLogout, openAlerts, open,
}) {
  const attention = useTwinResource("/issues/summary").data?.needs_attention ?? 0;
  const inMore = MORE.some((n) => n.id === view);
  const [moreOpen, setMoreOpen] = useState(inMore);
  useEffect(() => { if (inMore) setMoreOpen(true); }, [inMore]);      // opening one of these pages from a link shows its group
  const item = (n) => (
    <button key={n.id} className={`nav-item${view === n.id ? " active" : ""}`} onClick={() => onView(n.id)}
            aria-current={view === n.id ? "page" : undefined}>
      {n.icon}<span>{n.label}</span>
      {n.badgeKey === "open" && openAlerts > 0 && (
        <span className="badge soft" aria-label={`${openAlerts} open issues`}>{openAlerts}</span>
      )}
      {n.badgeKey === "attention" && attention > 0 && (
        <span className="badge soft" aria-label={`${attention} issues need attention`}>{attention}</span>
      )}
    </button>
  );
  return (
    <aside className={`sidebar${open ? " open" : ""}`} aria-label="Navigation">
      <div className="brand brand-logo">
        <Logo onDark height={48} />
        <div className="brand-sub">Utilities Management Agent</div>
      </div>

      <nav className="nav" aria-label="Plant">
        <div className="nav-section">Plant team</div>
        {PLANT.map(item)}
      </nav>

      <nav className="nav" aria-label="Setup and information">
        <button type="button" className="nav-section nav-toggle" aria-expanded={moreOpen} onClick={() => setMoreOpen((o) => !o)}>
          Setup and information <IconChevron width={12} height={12} />
        </button>
        {moreOpen && MORE.map(item)}
      </nav>

      <button className="btn primary block new-chat" onClick={onNewChat} disabled={busy}>
        <IconPlus width={16} height={16} /> Ask the agent
      </button>

      <div className="sessions-head">Recent chats</div>
      <div className="sessions" role="list">
        {sessions.length === 0 && <p className="sessions-empty">No chats yet. Ask the agent anything about your utilities.</p>}
        {sessions.map((s) => (
          <SessionItem key={s.id} session={s} active={s.id === activeId && view === "chat"} disabled={busy}
                       onOpen={onOpen} onRename={onRename} onDelete={onDelete} />
        ))}
      </div>

      <div className="user-card">
        <span className="avatar" aria-hidden="true">{initials(user.name)}</span>
        <div className="user-text">
          <div className="user-name">{user.name}</div>
          <div className="user-email">{user.email}</div>
        </div>
        <button className="icon-btn" onClick={onLogout} aria-label="Sign out" title="Sign out"><IconLogout /></button>
      </div>
    </aside>
  );
}
