import { useState, useRef, useEffect } from "react";
import type { RagSource } from "./api";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: RagSource[];
}

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (question: string) => void;
  onClose: () => void;
  loading: boolean;
  error: string | null;
}

export default function ChatPanel({ messages, onSend, onClose, loading, error }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [expandedSources, setExpandedSources] = useState<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q || loading) return;
    setInput("");
    onSend(q);
  };

  const panelWidth = 380;
  const styles = {
    panel: {
      width: panelWidth,
      height: "100vh",
      background: "#0f172a",
      borderLeft: "1px solid #1e293b",
      display: "flex",
      flexDirection: "column" as const,
      flexShrink: 0,
    },
    header: {
      padding: "16px 20px",
      borderBottom: "1px solid #1e293b",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
    },
    title: { fontSize: 18, fontWeight: 700, color: "#e2e8f0" },
    closeBtn: {
      padding: "6px 12px",
      fontSize: 13,
      background: "#334155",
      color: "#94a3b8",
      border: "1px solid #475569",
      borderRadius: 6,
      cursor: "pointer",
    },
    messages: {
      flex: 1,
      overflowY: "auto" as const,
      padding: 16,
      display: "flex",
      flexDirection: "column" as const,
      gap: 16,
    },
    bubble: (role: "user" | "assistant") => ({
      alignSelf: role === "user" ? "flex-end" : "flex-start",
      maxWidth: "90%",
      padding: "12px 16px",
      borderRadius: 12,
      fontSize: 14,
      lineHeight: 1.5,
      background: role === "user" ? "#334155" : "#1e293b",
      color: "#e2e8f0",
      border: role === "user" ? "1px solid #475569" : "1px solid #334155",
    }),
    sourcesToggle: {
      marginTop: 10,
      padding: "6px 10px",
      fontSize: 12,
      background: "#334155",
      color: "#94a3b8",
      border: "1px solid #475569",
      borderRadius: 6,
      cursor: "pointer",
    },
    sourcesList: {
      marginTop: 8,
      padding: 10,
      background: "#0f172a",
      border: "1px solid #334155",
      borderRadius: 8,
      fontSize: 12,
      color: "#94a3b8",
    },
    sourceItem: { marginBottom: 8 },
    loadingBubble: {
      alignSelf: "flex-start",
      padding: "12px 16px",
      borderRadius: 12,
      fontSize: 14,
      background: "#1e293b",
      color: "#94a3b8",
      border: "1px solid #334155",
    },
    errorBanner: {
      padding: "10px 16px",
      margin: 16,
      background: "#7f1d1d",
      color: "#fecaca",
      borderRadius: 8,
      fontSize: 13,
    },
    form: {
      padding: 16,
      borderTop: "1px solid #1e293b",
    },
    formRow: {
      display: "flex",
      gap: 8,
      alignItems: "flex-end",
    },
    input: {
      flex: 1,
      padding: "10px 14px",
      fontSize: 14,
      background: "#1e293b",
      color: "#e2e8f0",
      border: "1px solid #334155",
      borderRadius: 8,
      outline: "none",
    },
    sendBtn: {
      padding: "10px 18px",
      fontSize: 14,
      fontWeight: 600,
      background: "#6366f1",
      color: "#fff",
      border: "none",
      borderRadius: 8,
      cursor: "pointer",
    },
  };

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span style={styles.title}>RAG Chat</span>
        <button type="button" onClick={onClose} style={styles.closeBtn}>
          Close
        </button>
      </div>

      {error && <div style={styles.errorBanner}>{error}</div>}

      <div style={styles.messages}>
        {messages.length === 0 && !loading && (
          <div style={{ color: "#64748b", fontSize: 14, textAlign: "center" as const, padding: 24 }}>
            Ask a question about the email graph. Answers use retrieved emails and relationships.
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i}>
            <div style={styles.bubble(msg.role)}>
              <div style={{ whiteSpace: "pre-wrap" }}>{msg.content}</div>
              {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
                <>
                  <button
                    type="button"
                    style={styles.sourcesToggle}
                    onClick={() => setExpandedSources(expandedSources === i ? null : i)}
                  >
                    {expandedSources === i ? "Hide sources" : `Show ${msg.sources.length} source(s)`}
                  </button>
                  {expandedSources === i && (
                    <div style={styles.sourcesList}>
                      {msg.sources.map((s, j) => (
                        <div key={j} style={styles.sourceItem}>
                          <strong>{s.namespace ?? "?"}</strong>
                          {s.score != null && ` · score ${s.score.toFixed(3)}`}
                          {s.type && ` · ${s.type}`}
                          <div style={{ marginTop: 4, color: "#cbd5e1" }}>
                            {(s.text_preview ?? "").slice(0, 200)}
                            {(s.text_preview?.length ?? 0) > 200 ? "…" : ""}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div style={styles.loadingBubble}>Thinking…</div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <form style={styles.form} onSubmit={handleSubmit}>
        <div style={styles.formRow}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about emails or relationships…"
            style={styles.input}
            disabled={loading}
          />
          <button type="submit" style={styles.sendBtn} disabled={loading || !input.trim()}>
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
