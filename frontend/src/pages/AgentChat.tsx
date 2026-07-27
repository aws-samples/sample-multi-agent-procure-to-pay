// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Send, Plus, MessageSquare, Wrench, Trash2 } from "lucide-react";
import { useAuth } from "../AuthContext";
import { api } from "../api";
import { resolveRole, getChatSuggestions, getChatSystemContext } from "../roles";
import { useTranslation } from "react-i18next";

interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  toolsUsed?: string[];
  streaming?: boolean; // true while assistant message is still streaming
}

interface ChatSession {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: string;
}

/** Render a line of text with basic markdown: **bold** */
function renderLine(line: string, key: number) {
  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  return (
    <span key={key}>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i}>{part.slice(2, -2)}</strong>;
        }
        return <span key={i}>{part}</span>;
      })}
      <br />
    </span>
  );
}

const ROLE_TITLES: Record<string, { title: string; desc: string; icon: string }> = {
  requester: {
    title: "Procurement Assistant",
    desc: "Describe what you need and I'll create a purchase requisition for you.",
    icon: "🏭",
  },
  approver: {
    title: "Approval Intelligence",
    desc: "Ask about pending approvals, risk scores, spend analysis, and agent recommendations.",
    icon: "✅",
  },
  ap_clerk: {
    title: "AP Assistant",
    desc: "Query invoice status, match results, payment schedules, and vendor balances.",
    icon: "🧾",
  },
  executive: {
    title: "Executive Intelligence",
    desc: "Get high-level P2P metrics, spend trends, ROI analysis, and pipeline health.",
    icon: "📊",
  },
  procurement: {
    title: "Procurement Intelligence",
    desc: "Analyze vendors, sourcing opportunities, PO status, and supply chain metrics.",
    icon: "🔍",
  },
  admin: {
    title: "P2P Intelligence Agent",
    desc: "Full access to all procurement data. Ask me anything.",
    icon: "⚡",
  },
};

export default function AgentChat() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const role = resolveRole(user?.role);
  const chatConfig = ROLE_TITLES[role] || ROLE_TITLES.admin;
  const suggestions = getChatSuggestions(role);

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>(() =>
    `chat_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`
  );
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "system",
      content: `${chatConfig.icon} ${chatConfig.title} ready. ${chatConfig.desc}`,
      timestamp: new Date().toISOString(),
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load sessions from backend on mount
  useEffect(() => {
    api.getChatSessions().then(({ sessions: s }) => {
      setSessions(s.map((x: any) => ({
        id: x.id,
        title: x.title,
        lastMessage: x.last_message || "",
        timestamp: x.timestamp,
      })));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, activeTool]);

  // ─── Chat via Lambda with typewriter effect ───────────────────────────────

  const typewriterRef = useRef<number | null>(null);

  const handleSyncSend = useCallback(async (text: string): Promise<string | undefined> => {
    setLoading(true);
    try {
      const roleContext = getChatSystemContext(role, user?.username || "unknown", user?.sapUser || "");
      const history = messages
        .filter(m => m.role === "user" || m.role === "assistant")
        .slice(-4)
        .map(m => ({ role: m.role, content: m.content }));
      const result = await api.chatWithAgent(text, role, roleContext, history, activeSessionId);
      const fullText = result.response || "No response.";
      const generatedTitle: string | undefined = result.generated_title;

      // Add assistant message and typewriter-reveal it
      setLoading(false);
      setMessages(prev => [
        ...prev,
        { role: "assistant", content: "", timestamp: new Date().toISOString(), streaming: true },
      ]);

      let charIdx = 0;
      const chunkSize = 3;
      const tick = () => {
        charIdx = Math.min(charIdx + chunkSize, fullText.length);
        setMessages(prev => {
          const msgs = [...prev];
          const last = msgs[msgs.length - 1];
          if (last.role === "assistant") {
            msgs[msgs.length - 1] = {
              ...last,
              content: fullText.slice(0, charIdx),
              streaming: charIdx < fullText.length,
            };
          }
          return msgs;
        });
        if (charIdx < fullText.length) {
          typewriterRef.current = window.setTimeout(tick, 12);
        }
      };
      tick();
      return generatedTitle;
    } catch (e: any) {
      setLoading(false);
      setMessages(prev => [
        ...prev,
        { role: "assistant", content: `Error: ${(e as Error).message}`, timestamp: new Date().toISOString() },
      ]);
      return undefined;
    }
  }, [role, user, messages]);

  // ─── Send handler ─────────────────────────────────────────────────────────

  const handleSend = useCallback(async (text?: string) => {
    const msg = (text || input).trim();
    if (!msg || loading) return;
    setMessages(prev => [...prev, { role: "user", content: msg, timestamp: new Date().toISOString() }]);
    setInput("");

    // Messages are persisted server-side in the /agents/chat endpoint

    const generatedTitle = await handleSyncSend(msg);

    // Update session list in UI — use Haiku-generated title if available
    setSessions(prev => {
      const existing = prev.find(s => s.id === activeSessionId);
      if (existing) {
        return prev.map(s =>
          s.id === activeSessionId
            ? {
                ...s,
                title: generatedTitle || s.title,
                lastMessage: msg.substring(0, 60),
                timestamp: new Date().toISOString(),
              }
            : s
        );
      }
      return [
        {
          id: activeSessionId,
          title: generatedTitle || msg.substring(0, 40),
          lastMessage: msg.substring(0, 60),
          timestamp: new Date().toISOString(),
        },
        ...prev,
      ].slice(0, 20);
    });
  }, [input, loading, handleSyncSend, activeSessionId]);

  // ─── Session management ───────────────────────────────────────────────────

  const startNewChat = useCallback(() => {
    abortRef.current?.abort();
    const newId = `chat_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
    setActiveSessionId(newId);
    setMessages([{
      role: "system",
      content: `${chatConfig.icon} ${chatConfig.title} ready. ${chatConfig.desc}`,
      timestamp: new Date().toISOString(),
    }]);
    setInput("");
    setActiveTool(null);
    setLoading(false);
  }, [chatConfig]);

  const switchSession = useCallback(async (sessionId: string) => {
    abortRef.current?.abort();
    setActiveSessionId(sessionId);
    setInput("");
    setActiveTool(null);
    setLoading(false);

    // Load messages from backend
    setMessages([{
      role: "system",
      content: `${chatConfig.icon} Loading conversation...`,
      timestamp: new Date().toISOString(),
    }]);

    try {
      const { messages: saved } = await api.getChatMessages(sessionId);
      setMessages([
        {
          role: "system",
          content: `${chatConfig.icon} ${chatConfig.title} ready. ${chatConfig.desc}`,
          timestamp: new Date().toISOString(),
        },
        ...saved.map((m: any) => ({
          role: m.role as "user" | "assistant",
          content: m.content,
          timestamp: m.timestamp,
          toolsUsed: m.tools_used || [],
        })),
      ]);
    } catch {
      setMessages([{
        role: "system",
        content: `${chatConfig.icon} ${chatConfig.title} ready. ${chatConfig.desc}`,
        timestamp: new Date().toISOString(),
      }]);
    }
  }, [chatConfig]);

  return (
    <div className="animate-in space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{chatConfig.icon} {chatConfig.title}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {chatConfig.desc}
          </p>
        </div>
        <Button variant="outline" onClick={startNewChat}>
          <Plus className="h-4 w-4 mr-1.5" />
          New Chat
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr_280px] gap-5">
        {/* Left: Chat history sidebar */}
        <div className="hidden lg:block">
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
            {t("agentChat.ui.recentChats")}
          </div>
          <div className="flex flex-col gap-1.5">
            {sessions.length === 0 && (
              <div className="text-xs text-muted-foreground italic px-2 py-3">
                {t("agentChat.ui.noPreviousChats")}
              </div>
            )}
            {sessions.map(session => (
              <div
                key={session.id}
                className={`group relative w-full text-left rounded-md px-2.5 py-2 text-xs transition-colors cursor-pointer ${
                  session.id === activeSessionId
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
                onClick={() => switchSession(session.id)}
                role="button"
                tabIndex={0}
                onKeyDown={e => { if (e.key === "Enter") switchSession(session.id); }}
              >
                <div className="flex items-center gap-1.5">
                  <MessageSquare className="h-3 w-3 shrink-0" />
                  <span className="truncate font-medium flex-1">{session.title}</span>
                  <button
                    className="hidden group-hover:inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                    onClick={(e) => {
                      e.stopPropagation();
                      api.deleteChatSession(session.id).catch(() => {});
                      setSessions(prev => prev.filter(s => s.id !== session.id));
                      if (session.id === activeSessionId) startNewChat();
                    }}
                    title="Delete chat"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
                <div className="truncate mt-0.5 opacity-70">{session.lastMessage}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Center: Chat panel */}
        <div className="rounded-lg border bg-card flex flex-col h-[560px]">
          {/* Chat header bar */}
          <div className="flex items-center gap-2 px-4 py-3 border-b">
            <div className="h-2.5 w-2.5 rounded-full bg-success animate-pulse" />
            <span className="text-sm font-medium">{chatConfig.title}</span>
            <Badge variant="info" className="ml-auto">{role}</Badge>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`text-sm ${
                  msg.role === "user"
                    ? "ml-auto max-w-[75%] rounded-lg bg-primary text-primary-foreground p-3"
                    : msg.role === "system"
                      ? "text-center text-xs text-muted-foreground py-2"
                      : "max-w-[85%] rounded-lg bg-muted p-3"
                }`}
              >
                {msg.role === "assistant" && (
                  <div className="text-xs font-semibold text-primary mb-1">{chatConfig.icon} {chatConfig.title}</div>
                )}
                {msg.role === "system" && msg.content}
                {msg.role !== "system" && msg.content.split("\n").map((line, j) => renderLine(line, j))}
                {/* Tool usage indicators */}
                {msg.toolsUsed && msg.toolsUsed.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {msg.toolsUsed.map((tool, ti) => (
                      <span key={ti} className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary">
                        <Wrench className="h-2.5 w-2.5" />
                        {tool}
                      </span>
                    ))}
                  </div>
                )}
                {/* Streaming cursor */}
                {msg.streaming && (
                  <span className="inline-block w-1.5 h-4 bg-primary animate-pulse ml-0.5 align-text-bottom" />
                )}
              </div>
            ))}

            {/* Active tool indicator */}
            {activeTool && (
              <div className="max-w-[85%] rounded-lg bg-muted/50 border border-dashed border-primary/30 p-2.5 text-xs text-muted-foreground">
                <div className="flex items-center gap-2">
                  <Wrench className="h-3.5 w-3.5 text-primary animate-spin" />
                  <span>{activeTool}</span>
                </div>
              </div>
            )}

            {/* Thinking indicator */}
            {loading && (
              <div className="max-w-[85%] rounded-lg bg-muted p-3 text-sm">
                <div className="text-xs font-semibold text-primary mb-1">{chatConfig.icon} {chatConfig.title}</div>
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <span className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: "300ms" }} />
                  </span>
                  <span className="text-xs ml-1">{t("agentChat.ui.thinking")}</span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input area */}
          <div className="flex items-center gap-2 p-3 border-t">
            <input
              className="flex-1 h-9 rounded-md border border-input bg-transparent px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder={role === "requester"
                ? "Describe what you need to order..."
                : "Ask about your procurement data..."
              }
              onKeyDown={e => { if (e.key === "Enter") handleSend(); }}
              disabled={loading}
            />
            <Button size="sm" onClick={() => handleSend()} disabled={!input.trim() || loading}>
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Right: Suggested queries */}
        <div>
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
            {role === "requester" ? "Quick Orders" : "Try Asking"}
          </div>
          <div className="flex flex-col gap-2">
            {suggestions.map((q, i) => (
              <div
                key={i}
                className="rounded-lg border bg-card p-3 cursor-pointer text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                onClick={() => handleSend(q)}
                role="button"
                tabIndex={0}
                onKeyDown={e => { if (e.key === "Enter") handleSend(q); }}
              >
                {q}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
