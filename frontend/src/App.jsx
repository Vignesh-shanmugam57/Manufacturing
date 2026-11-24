import { useCallback, useEffect, useRef, useState } from "react";
import { api, loadUser, saveUser, streamChat } from "./api/client.js";
import AgentActivity from "./components/AgentActivity.jsx";
import Architecture from "./components/flow/Architecture.jsx";
import Monitoring from "./components/flow/Monitoring.jsx";
import { TwinStatus } from "./components/twin/ui.jsx";
import AlertsPanel from "./components/AlertsPanel.jsx";
import ChatView from "./components/ChatView.jsx";
import Connectors from "./components/Connectors.jsx";
import DigitalTwin from "./components/twin/DigitalTwin.jsx";
import Issues from "./components/Issues.jsx";
import LoginScreen from "./components/LoginScreen.jsx";
import Sidebar from "./components/Sidebar.jsx";
import { IconMenu, IconMoon, IconSun } from "./components/icons.jsx";
import { useTheme } from "./hooks/useTheme.js";
import { cached, clearCache, invalidate, peekStale, setCached, setCacheScope } from "./lib/cache.js";
import { prefetchAll } from "./lib/prefetch.js";
import { startTwin, stopTwin } from "./lib/twin.js";

const TITLES = {
  issues: "Issues", map: "Plant map",
  architecture: "How it works", connectors: "Data connectors", flow: "Agent activity", assign: "Assign issues",
  monitor: "Plant overview",
};

export default function App() {
  // Load this user's saved data before the first render, so pages can show it immediately.
  const [user, setUser] = useState(() => {
    const u = loadUser();
    if (u) setCacheScope(u.id);
    return u;
  });
  const [theme, toggleTheme] = useTheme();
  const [view, setView] = useState("issues");
  const [mapFocus, setMapFocus] = useState(null);     // equipment the plant map should fly to when it opens
  const [pendingAsk, setPendingAsk] = useState(null);
  const [sessions, setSessions] = useState(() => peekStale("sessions") ?? []);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingSession, setLoadingSession] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(null);
  const [chatError, setChatError] = useState("");
  const [openAlerts, setOpenAlerts] = useState(() => peekStale("alerts-open")?.count ?? 0);
  const [hasData, setHasData] = useState(true); // assume yes until the status says otherwise (no flicker)
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const activeRef = useRef(null);
  activeRef.current = activeId;

  const logout = useCallback(() => {
    saveUser(null);
    setUser(null);
    setSessions([]);
    setMessages([]);
    setActiveId(null);
    setView("issues");
    clearCache();
    stopTwin();
  }, []);

  useEffect(() => {
    window.addEventListener("auth:expired", logout);
    return () => window.removeEventListener("auth:expired", logout);
  }, [logout]);

  const refreshSessions = useCallback(async () => {
    try { setSessions(await cached("sessions", () => api.listSessions(), { force: true })); } catch { /* shown elsewhere */ }
  }, []);
  const refreshAlertCount = useCallback(async () => {
    try { setOpenAlerts((await cached("alerts-open", () => api.alerts("open"), { force: true })).count); } catch { /* ignore */ }
  }, []);
  // Live alert badge: re-check every 15 s while the tab is visible (setting the same number again does not re-render).
  useEffect(() => {
    if (!user) return undefined;
    const id = setInterval(() => { if (document.visibilityState === "visible") refreshAlertCount(); }, 15_000);
    return () => clearInterval(id);
  }, [user, refreshAlertCount]);
  // Keep the saved copy of the chat list in step with what is on screen, so the next visit starts with it.
  useEffect(() => { if (user) setCached("sessions", sessions); }, [sessions, user]);

  const refreshDataStatus = useCallback(async () => {
    try {
      const st = await cached("dataStatus", api.dataStatus);
      setHasData(st.datasets.some((d) => d.dataset === "utility" && d.rows > 0));
    } catch { /* ignore */ }
  }, []);
  // New rows change every analysis, so drop the shared cache before the pages reload.
  const dataChanged = useCallback(() => { invalidate(); refreshDataStatus(); }, [refreshDataStatus]);

  useEffect(() => {
    if (!user) return;
    prefetchAll();
    startTwin();            // the live telemetry stream (SIMULATED until a real gateway pushes readings)
    refreshDataStatus();
    api.me().then((u) => { saveUser(u); }).catch(() => {});
    refreshSessions();
    refreshAlertCount();
  }, [user, refreshSessions, refreshAlertCount, refreshDataStatus]);

  function login(u) {
    saveUser(u);
    setCacheScope(u.id);
    setUser(u);
  }

  function go(next, arg) {
    if (next === "map") setMapFocus(arg || null);
    setView(next);
    setSidebarOpen(false);
  }

  function newChat() {
    setActiveId(null);
    setMessages([]);
    setChatError("");
    go("chat");
  }

  async function openSession(id) {
    go("chat");
    setActiveId(id);
    setChatError("");
    setMessages([]);
    setLoadingSession(true);
    try {
      const detail = await api.getSession(id);
      if (activeRef.current === id) setMessages(detail.messages);
    } catch (e) {
      setChatError(e.message);
    } finally {
      setLoadingSession(false);
    }
  }

  async function renameSession(id, title) {
    try {
      const updated = await api.renameSession(id, title);
      setSessions((list) => list.map((s) => (s.id === id ? updated : s)));
    } catch (e) {
      setChatError(e.message);
    }
  }

  async function deleteSession(id) {
    try {
      await api.deleteSession(id);
      setSessions((list) => list.filter((s) => s.id !== id));
      if (activeRef.current === id) newChat();
    } catch (e) {
      setChatError(e.message);
    }
  }

  const upsertSession = (s) => setSessions((list) => [s, ...list.filter((x) => x.id !== s.id)]);

  async function send(text) {
    if (busy) return false;
    setBusy(true);
    setChatError("");
    const tempId = `pending-${Date.now()}`;
    setMessages((m) => [...m, { id: tempId, role: "user", content: text, created_at: new Date().toISOString() }]);
    setProgress({ startedAt: Date.now(), steps: [], thinking: true });
    let ok = true;
    try {
      await streamChat({
        sessionId: activeId,
        message: text,
        onEvent: (type, data) => {
          if (type === "session") {
            setActiveId(data.session.id);
            upsertSession(data.session);
            setMessages((m) => m.map((x) => (x.id === tempId ? data.user_message : x)));
          } else if (type === "thinking") {
            setProgress((p) => p && { ...p, thinking: true });
          } else if (type === "tool_start") {
            setProgress((p) => p && { ...p, thinking: false, steps: [...p.steps, { step: data.step, tool: data.tool, status: "running" }] });
          } else if (type === "tool_end") {
            setProgress((p) => p && { ...p, steps: p.steps.map((s) => (s.step === data.step ? { ...s, status: data.ok ? "done" : "error" } : s)) });
          } else if (type === "final") {
            upsertSession(data.session);
            setMessages((m) => [
              ...m.filter((x) => x.id !== tempId && x.id !== data.user_message.id),
              data.user_message,
              data.assistant_message,
            ]);
          } else if (type === "error") {
            setChatError(data.detail);
            ok = false;
          }
        },
      });
    } catch (e) {
      setChatError(e.message);
      setMessages((m) => m.filter((x) => x.id !== tempId));
      ok = false;
    } finally {
      setBusy(false);
      setProgress(null);
      invalidate(); // the agent may have raised or verified alerts
      refreshAlertCount();
    }
    return ok;
  }

  // "Ask the agent" on the dashboard opens a fresh chat and sends the question once it is ready.
  function askAgent(text) {
    newChat();
    setPendingAsk(text);
  }
  useEffect(() => {
    if (pendingAsk && !busy) {
      const text = pendingAsk;
      setPendingAsk(null);
      send(text);
    }
  }, [pendingAsk]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!user) return <LoginScreen onLogin={login} theme={theme} onToggleTheme={toggleTheme} />;

  const activeSession = sessions.find((s) => s.id === activeId);
  const title = view === "chat" ? (activeSession?.title || "New chat") : TITLES[view];

  return (
    <div className="app">
      <Sidebar
        user={user} view={view} onView={go} sessions={sessions} activeId={activeId} busy={busy}
        onNewChat={newChat} onOpen={openSession} onRename={renameSession} onDelete={deleteSession}
        onLogout={logout} openAlerts={openAlerts} open={sidebarOpen}
      />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} aria-hidden="true" />}
      <main className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setSidebarOpen(true)} aria-label="Open menu"><IconMenu /></button>
          <h1 className="topbar-title" title={title}>{title}</h1>
          <TwinStatus />
          <button className="icon-btn" onClick={toggleTheme} aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}>
            {theme === "light" ? <IconMoon /> : <IconSun />}
          </button>
        </header>
        <div className="view">
          {view === "chat" && (
            <ChatView messages={messages} busy={busy} progress={progress} error={chatError}
                      loading={loadingSession} onSend={send} userName={user.name}
                      hasData={hasData} onOpenData={() => go("connectors")} />
          )}
          {view === "issues" && <Issues onGo={go} />}
          {view === "map" && <DigitalTwin focusId={mapFocus} />}
          {view === "architecture" && <Architecture onGo={go} />}
          {view === "connectors" && <Connectors onDataChanged={dataChanged} />}
          {view === "flow" && <AgentActivity onAlertsChanged={refreshAlertCount} onGo={go} />}
          {view === "assign" && <AlertsPanel onAlertsChanged={refreshAlertCount} />}
          {view === "monitor" && <Monitoring onGo={go} />}
        </div>
      </main>
    </div>
  );
}
