/**
 * Productivity-Friend Dashboard
 * ==============================
 * Bloomberg terminal-style TAM operations panel.
 * Designed to be embedded inside TruvBrain (Next.js / Vercel).
 *
 * Props:
 *   apiBaseUrl  {string}  URL of the running api_server.py
 *                         Default: http://localhost:8000
 *
 * To embed in TruvBrain, see truv-brain-integration/productivity-page.tsx
 *
 * Styling: dark background + amber monochrome, IBM Plex Mono, scanlines.
 * All styles are inline or injected via <style> — no Tailwind dependency.
 */

"use client";

import { useState, useEffect, useRef, useCallback } from "react";

// ── Theme tokens ──────────────────────────────────────────────────────────────
const T = {
  bg:        "#080b0e",
  bgPanel:   "#0d1117",
  bgInput:   "#111820",
  amber:     "#f5a623",
  amberDim:  "#a06b14",
  amberFaint:"#3d2b08",
  green:     "#22c55e",
  red:       "#ef4444",
  yellow:    "#eab308",
  blue:      "#38bdf8",
  muted:     "#4a5568",
  border:    "#1e2d3d",
  font:      "'IBM Plex Mono', 'Courier New', monospace",
};

// ── Priority → colour map ──────────────────────────────────────────────────
const PRIORITY_COLOR = {
  HIGH:     T.red,
  MEDIUM:   T.yellow,
  LOW:      T.green,
  SPAM:     T.muted,
  PHISHING: T.red,
};

const PRIORITY_ICON = {
  HIGH:     "●",
  MEDIUM:   "◐",
  LOW:      "○",
  SPAM:     "✕",
  PHISHING: "☠",
};

// ── Inline style helpers ───────────────────────────────────────────────────
const panel = (extra = {}) => ({
  background: T.bgPanel,
  border: `1px solid ${T.border}`,
  borderRadius: 4,
  padding: "10px 14px",
  overflow: "hidden",
  ...extra,
});

const label = (extra = {}) => ({
  fontFamily: T.font,
  fontSize: 10,
  letterSpacing: "0.12em",
  color: T.amberDim,
  textTransform: "uppercase",
  marginBottom: 6,
  ...extra,
});

const mono = (color = T.amber, size = 12) => ({
  fontFamily: T.font,
  fontSize: size,
  color,
  lineHeight: "1.55",
});

const dot = (alive) => ({
  display: "inline-block",
  width: 7,
  height: 7,
  borderRadius: "50%",
  background: alive ? T.green : T.red,
  marginRight: 6,
  flexShrink: 0,
});

// ── Scanline CSS injected once ─────────────────────────────────────────────
const SCANLINE_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap');

  .pf-root {
    position: relative;
    background: ${T.bg};
    color: ${T.amber};
    font-family: ${T.font};
    min-height: 100vh;
  }
  .pf-root::before {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,0,0,0.18) 2px,
      rgba(0,0,0,0.18) 4px
    );
    pointer-events: none;
    z-index: 9999;
  }
  .pf-scroll::-webkit-scrollbar { width: 4px; }
  .pf-scroll::-webkit-scrollbar-track { background: ${T.bg}; }
  .pf-scroll::-webkit-scrollbar-thumb { background: ${T.amberDim}; border-radius: 2px; }
  .pf-blink { animation: pf-blink 1s step-end infinite; }
  @keyframes pf-blink { 50% { opacity: 0; } }
`;

// ── Utility: fetch wrapper ─────────────────────────────────────────────────
async function apiFetch(baseUrl, path, opts = {}) {
  const secret = typeof window !== "undefined"
    ? window.__PF_SECRET__ || ""
    : "";
  const headers = {
    "Content-Type": "application/json",
    ...(secret ? { Authorization: `Bearer ${secret}` } : {}),
    ...opts.headers,
  };
  const resp = await fetch(`${baseUrl}${path}`, { ...opts, headers });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

// ── Sub-components ─────────────────────────────────────────────────────────

function StatBar({ stats }) {
  const items = [
    { label: "EMAILS QUEUED", value: stats.emailCount ?? "—" },
    { label: "HIGH PRIORITY", value: stats.highCount ?? "—", color: T.red },
    { label: "JSON ERRORS",   value: stats.jsonErrors ?? "—", color: stats.jsonErrors > 0 ? T.red : T.green },
    { label: "WEBHOOKS LIVE", value: stats.webhooksLive ?? "—", color: T.green },
    { label: "API STATUS",    value: stats.apiOk ? "ONLINE" : "OFFLINE", color: stats.apiOk ? T.green : T.red },
  ];

  return (
    <div style={{
      display: "flex",
      gap: 1,
      background: T.amberFaint,
      borderBottom: `1px solid ${T.border}`,
      padding: "5px 14px",
      flexWrap: "wrap",
    }}>
      {items.map((item) => (
        <div key={item.label} style={{
          padding: "2px 16px 2px 0",
          borderRight: `1px solid ${T.border}`,
          marginRight: 16,
        }}>
          <div style={label()}>{item.label}</div>
          <div style={{ ...mono(item.color || T.amber, 16), fontWeight: 600 }}>
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function EmailPanel({ emails, onScan, scanning }) {
  const high   = emails.filter((e) => e.priority === "HIGH");
  const medium = emails.filter((e) => e.priority === "MEDIUM");
  const low    = emails.filter((e) => e.priority === "LOW");
  const spam   = emails.filter((e) => ["SPAM","PHISHING"].includes(e.priority));

  return (
    <div style={panel({ display: "flex", flexDirection: "column", gap: 6 })}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={label()}>Email Queue</div>
        <button
          onClick={onScan}
          disabled={scanning}
          style={{
            ...mono(T.bg, 10),
            background: T.amber,
            border: "none",
            borderRadius: 2,
            padding: "2px 8px",
            cursor: scanning ? "wait" : "pointer",
            fontWeight: 600,
            letterSpacing: "0.08em",
          }}
        >
          {scanning ? "SCANNING…" : "SCAN"}
        </button>
      </div>

      {/* Summary row */}
      <div style={{ display: "flex", gap: 12, marginBottom: 4 }}>
        {[
          { label: "HIGH",  count: high.length,   color: T.red },
          { label: "MED",   count: medium.length, color: T.yellow },
          { label: "LOW",   count: low.length,    color: T.green },
          { label: "SPAM",  count: spam.length,   color: T.muted },
        ].map((b) => (
          <div key={b.label} style={{ textAlign: "center" }}>
            <div style={mono(b.color, 18)}>{b.count}</div>
            <div style={label({ marginBottom: 0 })}>{b.label}</div>
          </div>
        ))}
      </div>

      {/* Email list */}
      <div className="pf-scroll" style={{ overflowY: "auto", maxHeight: 220, flex: 1 }}>
        {emails.length === 0 ? (
          <div style={mono(T.muted, 11)}>No emails loaded — press SCAN</div>
        ) : (
          emails.slice(0, 30).map((e, i) => (
            <div key={e.id || i} style={{
              borderBottom: `1px solid ${T.amberFaint}`,
              padding: "4px 0",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ color: PRIORITY_COLOR[e.priority] || T.muted, fontSize: 10 }}>
                  {PRIORITY_ICON[e.priority] || "?"}
                </span>
                <span style={mono(T.amber, 11)} title={e.subject}>
                  {(e.subject || "(no subject)").slice(0, 42)}
                </span>
                {e.has_json_attachment && (
                  <span style={mono(T.blue, 10)} title="Has JSON attachment">📎</span>
                )}
              </div>
              <div style={mono(T.amberDim, 10)}>
                {(e.from || "").slice(0, 38)} · {e.reason?.slice(0, 40)}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function JsonInspectorPanel({ results }) {
  const latest = results[0];
  return (
    <div style={panel({ display: "flex", flexDirection: "column", gap: 6 })}>
      <div style={label()}>JSON Inspector</div>
      {!latest ? (
        <div style={mono(T.muted, 11)}>No JSON files processed yet.</div>
      ) : (
        <>
          <div style={mono(T.amber, 11)}>
            <span style={{ color: T.amberDim }}>FILE: </span>{latest.filename}
          </div>
          <div style={mono(T.amber, 11)}>
            <span style={{ color: T.amberDim }}>CUSTOMER: </span>{latest.customer_email}
          </div>
          <div style={mono(latest.was_fixed ? T.yellow : T.green, 11)}>
            STATUS: {latest.was_fixed ? `FIXED (${latest.validation_errors?.length} errors)` : "VALID ✓"}
          </div>

          {/* Errors */}
          <div className="pf-scroll" style={{ overflowY: "auto", maxHeight: 100, marginTop: 4 }}>
            {(latest.validation_errors || []).map((err, i) => (
              <div key={i} style={mono(T.red, 10)}>✗ {err.slice(0, 80)}</div>
            ))}
          </div>

          {/* Diff summary */}
          {latest.diff_report && latest.diff_report !== "No changes required — JSON was already valid." && (
            <div className="pf-scroll" style={{ overflowY: "auto", maxHeight: 60, marginTop: 4 }}>
              {latest.diff_report.split("\n").map((line, i) => (
                <div key={i} style={mono(T.yellow, 10)}>{line}</div>
              ))}
            </div>
          )}

          {/* PII */}
          <div style={mono(T.amberDim, 10)}>{latest.pii_summary?.split("\n")[0]}</div>
        </>
      )}

      {/* History list */}
      {results.length > 1 && (
        <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 6, marginTop: 4 }}>
          <div style={label()}>Recent Files</div>
          {results.slice(1, 6).map((r, i) => (
            <div key={i} style={mono(T.amberDim, 10)}>
              {r.filename} — {r.was_fixed ? `${r.validation_errors?.length} fixed` : "✓"}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WebhookMonitorPanel({ webhookLog }) {
  const events = ["task-status-updated", "order-status-updated"];
  const seenEvents = new Set(webhookLog.map((e) => e.type_name));

  return (
    <div style={panel({ display: "flex", flexDirection: "column", gap: 6 })}>
      <div style={label()}>Webhook Monitor</div>

      {/* Event type status */}
      {events.map((evt) => {
        const seen = webhookLog.find((l) => l.type_name === evt);
        const alive = Boolean(seen);
        return (
          <div key={evt} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={dot(alive)} />
            <span style={mono(alive ? T.green : T.muted, 11)}>{evt}</span>
            {alive && <span style={mono(T.amberDim, 10)}>{seen.ts}</span>}
          </div>
        );
      })}

      <div style={{ borderTop: `1px solid ${T.border}`, marginTop: 4, paddingTop: 6 }}>
        <div style={label()}>Recent Events</div>
        <div className="pf-scroll" style={{ overflowY: "auto", maxHeight: 120 }}>
          {webhookLog.length === 0 ? (
            <div style={mono(T.muted, 10)}>
              Point Truv webhook_url to:<br />
              http://&lt;your-ip&gt;:8000/truv/webhook
            </div>
          ) : (
            webhookLog.slice(0, 12).map((e, i) => (
              <div key={i} style={{ borderBottom: `1px solid ${T.amberFaint}`, padding: "2px 0" }}>
                <span style={mono(T.amberDim, 10)}>{e.ts} </span>
                <span style={mono(T.amber, 10)}>{e.type_name}</span>
                {e.status && <span style={mono(T.amberDim, 10)}> [{e.status}]</span>}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function N8nPipelinePanel({ n8nStatus }) {
  const pipelines = [
    { name: "EMAIL WATCH",  key: "email_watch",  desc: "Polls inbox every 5 min" },
    { name: "JSON PROC",    key: "json_proc",    desc: "Attachment processing"    },
    { name: "TRUV WEBHOOK", key: "truv_webhook", desc: "Receives Truv events"    },
    { name: "AUTO-REPLY",   key: "auto_reply",   desc: "Draft email sender"       },
  ];

  return (
    <div style={panel()}>
      <div style={label()}>n8n Pipeline Status</div>
      <div style={mono(T.amberDim, 10), { marginBottom: 8 }}>
        {n8nStatus.url || "N8N_BASE_URL not set"}
      </div>
      {pipelines.map((p) => {
        const active = n8nStatus[p.key] ?? false;
        return (
          <div key={p.key} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
            <span style={dot(active)} />
            <span style={mono(active ? T.amber : T.muted, 11)}>{p.name}</span>
            <span style={mono(T.amberDim, 10)}>— {p.desc}</span>
          </div>
        );
      })}
      <div style={{ marginTop: 8, ...mono(T.amberDim, 10) }}>
        n8n webhook receiver:<br />
        <span style={{ color: T.amber }}>POST /n8n/webhook</span>
      </div>
    </div>
  );
}

function TruvApiHealthPanel({ truvHealth }) {
  const endpoints = [
    { path: "/v1/orders",                label: "Orders (VOE/VOIE)" },
    { path: "/v1/users/{id}/tokens",     label: "Bridge Token" },
    { path: "/v1/verifications/income",  label: "Income Report" },
    { path: "/v1/verifications/employment", label: "Employment Report" },
    { path: "/v1/refresh/tasks",         label: "Data Refresh" },
    { path: "/v1/truv/webhook",          label: "Webhook Receiver" },
  ];

  return (
    <div style={panel()}>
      <div style={label()}>Truv API Health</div>
      <div style={mono(T.amberDim, 10), { marginBottom: 6 }}>
        Base: https://prod.truv.com/v1/
      </div>
      {endpoints.map((ep) => {
        const status = truvHealth[ep.path];
        const ok     = status === "ok" || status === true;
        const color  = status === undefined ? T.muted : ok ? T.green : T.red;
        return (
          <div key={ep.path} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
            <span style={dot(ok)} />
            <span style={mono(color, 11)}>{ep.label}</span>
          </div>
        );
      })}
      <div style={{ marginTop: 8, ...mono(T.amberDim, 9) }}>
        Auth: X-Access-Client-Id + X-Access-Secret headers
      </div>
    </div>
  );
}

function ActivityLogPanel({ activity }) {
  const typeColor = {
    email: T.blue, json: T.yellow, webhook: T.green,
    calendar: T.amber, n8n: T.blue, error: T.red,
  };

  return (
    <div style={panel({ display: "flex", flexDirection: "column" })}>
      <div style={label()}>Live Activity Log</div>
      <div className="pf-scroll" style={{ overflowY: "auto", flex: 1, maxHeight: 220 }}>
        {activity.length === 0 ? (
          <div style={mono(T.muted, 11)}>Waiting for activity…</div>
        ) : (
          activity.map((e, i) => (
            <div key={i} style={{ borderBottom: `1px solid ${T.amberFaint}`, padding: "3px 0" }}>
              <span style={mono(T.amberDim, 10)}>{e.ts} </span>
              <span style={mono(typeColor[e.type] || T.amber, 10)}>
                [{e.type?.toUpperCase()}]
              </span>
              <span style={mono(T.amber, 10)}> {e.message}</span>
              {e.detail && (
                <div style={mono(T.amberDim, 10)}>{e.detail}</div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function CommandBar({ onCommand }) {
  const [cmd, setCmd] = useState("");

  const handleKey = (e) => {
    if (e.key === "Enter" && cmd.trim()) {
      onCommand(cmd.trim());
      setCmd("");
    }
  };

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 8,
      background: T.bgInput,
      borderTop: `1px solid ${T.border}`,
      padding: "6px 14px",
    }}>
      <span style={mono(T.amberDim, 13)}>▸</span>
      <input
        value={cmd}
        onChange={(e) => setCmd(e.target.value)}
        onKeyDown={handleKey}
        placeholder='scan-inbox | daily-brief | process-json <file> | status'
        style={{
          flex: 1,
          background: "transparent",
          border: "none",
          outline: "none",
          ...mono(T.amber, 12),
          caretColor: T.amber,
        }}
      />
      <span className="pf-blink" style={mono(T.amber, 14)}>█</span>
    </div>
  );
}

// ── Main Dashboard Component ───────────────────────────────────────────────

export default function ProductivityFriendDashboard({
  apiBaseUrl = "http://localhost:8000",
}) {
  const [status,      setStatus]      = useState(null);
  const [emails,      setEmails]      = useState([]);
  const [calendar,    setCalendar]    = useState(null);
  const [jsonResults, setJsonResults] = useState([]);
  const [activity,    setActivity]    = useState([]);
  const [webhookLog,  setWebhookLog]  = useState([]);
  const [scanning,    setScanning]    = useState(false);
  const [cmdLog,      setCmdLog]      = useState([]);
  const [n8nStatus,   setN8nStatus]   = useState({});
  const [truvHealth,  setTruvHealth]  = useState({});
  const styleInjected = useRef(false);

  // Inject scanline CSS once
  useEffect(() => {
    if (styleInjected.current) return;
    const tag = document.createElement("style");
    tag.textContent = SCANLINE_CSS;
    document.head.appendChild(tag);
    styleInjected.current = true;
  }, []);

  // Poll status + activity every 30 s
  const pollStatus = useCallback(async () => {
    try {
      const s = await apiFetch(apiBaseUrl, "/api/status");
      setStatus(s);
      setN8nStatus((prev) => ({ ...prev, url: s.n8n_url_set ? apiBaseUrl : null }));
    } catch { /* server offline */ }

    try {
      const a = await apiFetch(apiBaseUrl, "/api/activity?limit=80");
      setActivity(a.activity || []);

      // Extract webhook events from activity log
      const wh = (a.activity || [])
        .filter((e) => e.type === "webhook")
        .map((e) => ({
          ts: e.ts,
          type_name: e.message.replace("Truv webhook: ", "").replace("Truv event: ", ""),
          status: e.detail,
        }));
      setWebhookLog(wh);
    } catch { /* ignore */ }
  }, [apiBaseUrl]);

  useEffect(() => {
    pollStatus();
    const id = setInterval(pollStatus, 30_000);
    return () => clearInterval(id);
  }, [pollStatus]);

  // Scan inbox handler
  const handleScan = async () => {
    setScanning(true);
    try {
      const data = await apiFetch(apiBaseUrl, "/api/scan-inbox", {
        method: "POST",
        body: JSON.stringify({ top: 20, auto_draft: false, auto_clean: false }),
      });
      setEmails(data.emails || []);
      await pollStatus();
    } catch (err) {
      setCmdLog((prev) => [`ERROR: ${err.message}`, ...prev]);
    } finally {
      setScanning(false);
    }
  };

  // Command bar handler
  const handleCommand = async (cmd) => {
    const parts = cmd.toLowerCase().split(/\s+/);
    const verb  = parts[0];
    setCmdLog((prev) => [`> ${cmd}`, ...prev]);

    try {
      if (verb === "scan-inbox" || verb === "scan") {
        await handleScan();
        setCmdLog((prev) => [`  Inbox scan complete. ${emails.length} emails.`, ...prev]);

      } else if (verb === "daily-brief" || verb === "calendar") {
        const data = await apiFetch(apiBaseUrl, "/api/daily-brief");
        setCalendar(data);
        setCmdLog((prev) => [
          `  Calendar: ${data.event_count} events. ${data.todo_list?.length || 0} to-dos.`,
          ...prev,
        ]);

      } else if (verb === "status") {
        await pollStatus();
        setCmdLog((prev) => [
          `  API: ${status?.status || "unknown"} | Anthropic: ${status?.anthropic_key_set ? "✓" : "✗"} | Graph: ${status?.microsoft_graph_set ? "✓" : "✗"}`,
          ...prev,
        ]);

      } else if (verb === "meeting-prep") {
        const data = await apiFetch(apiBaseUrl, "/api/meeting-prep");
        setCmdLog((prev) => [`  Meeting prep: ${data.count} briefs generated.`, ...prev]);

      } else if (verb === "clear") {
        setCmdLog([]);

      } else if (verb === "help") {
        setCmdLog((prev) => [
          "  Commands: scan-inbox | daily-brief | meeting-prep | status | clear",
          ...prev,
        ]);

      } else {
        setCmdLog((prev) => [`  Unknown command: ${verb}. Type 'help' for options.`, ...prev]);
      }
    } catch (err) {
      setCmdLog((prev) => [`  ERROR: ${err.message}`, ...prev]);
    }
  };

  // Derived stats
  const stats = {
    emailCount:   emails.length,
    highCount:    emails.filter((e) => e.priority === "HIGH").length,
    jsonErrors:   jsonResults.reduce((n, r) => n + (r.validation_errors?.length || 0), 0),
    webhooksLive: webhookLog.filter((w) =>
      ["task-status-updated", "order-status-updated"].includes(w.type_name)
    ).length,
    apiOk: status?.status === "ok",
  };

  return (
    <div className="pf-root" style={{ minHeight: "100vh" }}>

      {/* ── Header bar ────────────────────────────────────────────────────── */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 14px",
        borderBottom: `1px solid ${T.border}`,
        background: T.bgPanel,
      }}>
        <div style={{ ...mono(T.amber, 13), fontWeight: 700, letterSpacing: "0.2em" }}>
          ◈ PRODUCTIVITY-FRIEND  |  TRUV TAM OPS TERMINAL
        </div>
        <div style={mono(T.amberDim, 11)}>
          {new Date().toLocaleTimeString("en-US", { hour12: false })}
          {" "}
          <span style={{ color: status?.status === "ok" ? T.green : T.red }}>
            {status?.status === "ok" ? "● CONNECTED" : "○ OFFLINE"}
          </span>
        </div>
      </div>

      {/* ── Stat bar ──────────────────────────────────────────────────────── */}
      <StatBar stats={stats} />

      {/* ── Main grid ─────────────────────────────────────────────────────── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gridTemplateRows: "auto auto",
        gap: 8,
        padding: 8,
      }}>
        <EmailPanel     emails={emails}     onScan={handleScan} scanning={scanning} />
        <JsonInspectorPanel results={jsonResults} />
        <WebhookMonitorPanel webhookLog={webhookLog} />
        <N8nPipelinePanel n8nStatus={n8nStatus} />
        <TruvApiHealthPanel truvHealth={truvHealth} />
        <ActivityLogPanel   activity={activity} />
      </div>

      {/* ── Calendar strip (shown if daily brief loaded) ───────────────────── */}
      {calendar && (
        <div style={{ padding: "0 8px 8px" }}>
          <div style={panel({ display: "flex", gap: 24, flexWrap: "wrap" })}>
            <div>
              <div style={label()}>Today — {calendar.date}</div>
              <div style={mono(T.amber, 12)}>{calendar.event_count} events</div>
            </div>
            <div style={{ flex: 1 }}>
              <div style={label()}>To-Do</div>
              {(calendar.todo_list || []).slice(0, 5).map((item, i) => (
                <div key={i} style={mono(T.amber, 11)}>• {item}</div>
              ))}
            </div>
            <div style={{ flex: 1 }}>
              <div style={label()}>Focus Blocks</div>
              {(calendar.suggested_time_blocks || []).slice(0, 3).map((b, i) => (
                <div key={i} style={mono(T.amberDim, 11)}>
                  {typeof b === "object" ? `${b.time || b.start || ""} — ${b.purpose || ""}` : b}
                </div>
              ))}
            </div>
            {calendar.conflicts?.length > 0 && (
              <div>
                <div style={label({ color: T.red })}>Conflicts</div>
                {calendar.conflicts.map((c, i) => (
                  <div key={i} style={mono(T.red, 10)}>
                    ⚠ {c.event_a?.subject} ↔ {c.event_b?.subject}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Command log (above input bar) ─────────────────────────────────── */}
      {cmdLog.length > 0 && (
        <div style={{
          ...panel({ margin: "0 8px 0", borderBottom: "none", borderRadius: "4px 4px 0 0" }),
          maxHeight: 80,
          overflowY: "auto",
        }}>
          {cmdLog.slice(0, 10).map((line, i) => (
            <div key={i} style={mono(i === 0 && line.startsWith(">") ? T.amberDim : T.amber, 11)}>
              {line}
            </div>
          ))}
        </div>
      )}

      {/* ── Command input bar ─────────────────────────────────────────────── */}
      <CommandBar onCommand={handleCommand} />
    </div>
  );
}
