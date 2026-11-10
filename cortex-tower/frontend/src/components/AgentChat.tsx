import { useState, useEffect, useRef, useCallback } from "react";
import { Send, Plus, MessageSquare, Paperclip, ThumbsUp, ThumbsDown, ExternalLink, Loader2 } from "lucide-react";

// Collision-proof message ids. NEVER call Date.now() inside a state updater:
// React may flush the updater a millisecond later, so `Date.now()` there can match
// a sibling id computed earlier — which made the streaming reply overwrite the
// user's own question bubble.
let _msgSeq = 0;
function newMsgId(): string {
  _msgSeq += 1;
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  } catch { /* fall through */ }
  return `${Date.now()}-${_msgSeq}-${Math.random().toString(36).slice(2, 8)}`;
}
import { callApi, ChatConfig, streamMessage, cleanBoatReply } from "../services/api";

interface Thread { _id: string; title: string; summary: string; dateCategory: string; unread_count: number; }
// FIXED CONTRACT — canonical card shape used by ALL THREE layers (backend send_message,
// api.ts streamMessage, this component). The agent emits `cardContent` as an object:
//   { card_data: [ { card_content: { item_info: {...} } } ], file_datas: [...] }
// Each rendered CardItem is mapped from one card_data[i].card_content.item_info as:
//   title       <- item_info.title
//   description <- item_info.description
//   url         <- item_info.url
//   image       <- item_info.image
// This mapping (item_info -> CardItem) is performed once, in mapCardContent() below,
// and the component renders CardItem[] only.
interface CardItem { title?: string; description?: string; url?: string; image?: string; [key: string]: any; }
interface FileChip { name: string; url?: string; type?: string; }

// Map the agent's cardContent contract object to the flat CardItem[] the UI renders.
function mapCardContent(cardContent: any): CardItem[] | null {
  const cards = cardContent?.card_data;
  if (!Array.isArray(cards) || cards.length === 0) return null;
  return cards.map((c: any) => {
    const info = c?.card_content?.item_info || {};
    return { title: info.title, description: info.description, url: info.url, image: info.image };
  });
}
function mapFileDatas(cardContent: any): FileChip[] | null {
  const files = cardContent?.file_datas;
  if (!Array.isArray(files) || files.length === 0) return null;
  return files.map((f: any) => ({ name: f.file_name || f.name, url: f.file_path || f.url, type: f.file_type || f.type }));
}
interface Message {
  id: string;
  role: "user" | "agent";
  text: string;
  agentName?: string;
  agentIcon?: string;
  streaming?: boolean;
  cardData?: CardItem[] | null;
  fileDatas?: FileChip[] | null;
  likeStatus?: "liked" | "disliked" | null;
}

export default function AgentChat({ initialInput }: { initialInput?: string } = {}) {
  const [config, setConfig] = useState<ChatConfig | null>(null);
  const [roomId, setRoomId] = useState<string | null>(null);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState(initialInput || "");
  const [streaming, setStreaming] = useState(false);
  const [threadTitle, setThreadTitle] = useState("New Chat");
  const [searchQuery, setSearchQuery] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  useEffect(() => { scrollToBottom(); }, [messages]);

  useEffect(() => {
    (async () => {
      const cfgRes = await callApi("get_chat_config");
      if (!cfgRes.success) return;
      const cfg = cfgRes.data as ChatConfig;
      setConfig(cfg);
      const roomRes = await callApi("create_room");
      if (!roomRes.success) return;
      const rid = roomRes.data.room_id;
      setRoomId(rid);
      const threadsRes = await callApi("fetch_threads", { room_id: rid });
      if (threadsRes.success) setThreads(threadsRes.data.threads || []);
    })();
  }, []);

  const loadThread = useCallback(async (threadId: string, title: string) => {
    setActiveThreadId(threadId);
    setThreadTitle(title);
    const res = await callApi("fetch_chat_history", { thread_id: threadId });
    if (!res.success) return;
    const chats = res.data.chats || [];
    setMessages(chats.map((c: any) => ({
      id: c._id,
      role: c.isHumanReply || !c.agent ? "user" : "agent",
      text: cleanBoatReply(c.message || ""),
      agentName: c.agent?.name,
      agentIcon: c.agent?.icon,
    })));
  }, []);

  const sendMsg = useCallback(async () => {
    if (!input.trim() || streaming || !config) return;
    const userText = input.trim();
    setInput("");
    // Compute BOTH ids up-front (outside the updaters) so they can never collide.
    const userMsgId = newMsgId();
    const agentMsgId = newMsgId();
    setMessages(prev => [...prev, { id: userMsgId, role: "user", text: userText }]);
    setStreaming(true);
    setMessages(prev => [...prev, { id: agentMsgId, role: "agent", text: "", streaming: true }]);

    let capturedThreadId = activeThreadId;

    await streamMessage(config, userText, activeThreadId, {
      onChunk: (_, fullReply, repliedAgent) => {
        setMessages(prev => prev.map(m =>
          (m.role === "agent" && m.id === agentMsgId) ? { ...m, text: fullReply, agentName: repliedAgent?.name, agentIcon: repliedAgent?.icon } : m
        ));
      },
      onFinal: (fullReply, repliedAgent, cardContent) => {
        setMessages(prev => prev.map(m =>
          (m.role === "agent" && m.id === agentMsgId) ? {
            ...m,
            text: fullReply,
            streaming: false,
            agentName: repliedAgent?.name,
            agentIcon: repliedAgent?.icon,
            cardData: mapCardContent(cardContent),
            fileDatas: mapFileDatas(cardContent),
          } : m
        ));
      },
      onThreadId: (tid) => {
        capturedThreadId = tid;
        setActiveThreadId(tid);
        setThreadTitle("New conversation");
      },
      onError: (err) => {
        setMessages(prev => prev.map(m => (m.role === "agent" && m.id === agentMsgId) ? { ...m, text: `Error: ${err}`, streaming: false } : m));
      },
    });

    setStreaming(false);
    if (roomId) {
      const threadsRes = await callApi("fetch_threads", { room_id: roomId });
      if (threadsRes.success) setThreads(threadsRes.data.threads || []);
    }
  }, [input, streaming, config, activeThreadId, roomId]);

  const filteredThreads = threads.filter(t =>
    (t.title || t.summary || "").toLowerCase().includes(searchQuery.toLowerCase())
  );

  const groupedThreads = filteredThreads.reduce((acc: Record<string, Thread[]>, t) => {
    const cat = t.dateCategory || "Older";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(t);
    return acc;
  }, {});

  const categoryOrder = ["Today", "Yesterday", "Previous 7 Days", "Older"];
  // Catch-all: any dateCategory the server returns that is NOT in categoryOrder gets
  // rendered after the known buckets so no thread silently vanishes.
  const extraCategories = Object.keys(groupedThreads).filter(c => !categoryOrder.includes(c));
  const renderOrder = [...categoryOrder, ...extraCategories];

  return (
    <div style={{ display: "flex", height: "100%", background: "#F8F9FA", fontFamily: "'Space Grotesk', sans-serif" }}>
      {/* Sidebar */}
      <div style={{ width: 260, background: "#fff", borderRight: "1px solid #E5E7EB", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "16px 12px 8px", borderBottom: "1px solid #E5E7EB" }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: "#1F2937", marginBottom: 8 }}>
            {config?.agent_name || "Agent Chat"}
          </div>
          <button
            onClick={() => { setActiveThreadId(null); setMessages([]); setThreadTitle("New Chat"); }}
            style={{ width: "100%", padding: "6px 10px", background: "#3B82F6", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}
          >
            <Plus size={14} /> New Chat
          </button>
        </div>
        <div style={{ padding: "8px 12px" }}>
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search threads..."
            style={{ width: "100%", padding: "6px 8px", border: "1px solid #E5E7EB", borderRadius: 6, fontSize: 12, outline: "none", boxSizing: "border-box" }}
          />
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 8px" }}>
          {renderOrder.map(cat => {
            const group = groupedThreads[cat];
            if (!group?.length) return null;
            return (
              <div key={cat}>
                <div style={{ fontSize: 10, fontWeight: 600, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: "0.05em", padding: "8px 4px 4px" }}>{cat}</div>
                {group.map(t => (
                  <div
                    key={t._id}
                    onClick={() => loadThread(t._id, t.title || t.summary || "Conversation")}
                    style={{
                      padding: "8px 8px", borderRadius: 6, cursor: "pointer", marginBottom: 2,
                      background: activeThreadId === t._id ? "#EFF6FF" : "transparent",
                      borderLeft: activeThreadId === t._id ? "3px solid #3B82F6" : "3px solid transparent",
                    }}
                  >
                    <div style={{ fontSize: 12, color: "#1F2937", fontWeight: activeThreadId === t._id ? 600 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {t.title || t.summary || "Conversation"}
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
          {threads.length === 0 && (
            <div style={{ textAlign: "center", color: "#9CA3AF", fontSize: 12, padding: 16 }}>No conversations yet</div>
          )}
        </div>
      </div>

      {/* Chat Area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "12px 20px", borderBottom: "1px solid #E5E7EB", background: "#fff", fontWeight: 600, fontSize: 14, color: "#1F2937" }}>
          {threadTitle}
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
          {messages.length === 0 && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#9CA3AF" }}>
              <MessageSquare size={32} style={{ marginBottom: 8, opacity: 0.4 }} />
              <div style={{ fontSize: 14 }}>Start a conversation</div>
            </div>
          )}
          {messages.map(msg => (
            <div key={msg.id} style={{ display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start", gap: 8 }}>
              {msg.role === "agent" && (
                <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#E5E7EB", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, flexShrink: 0, overflow: "hidden" }}>
                  {msg.agentIcon ? <img src={msg.agentIcon} style={{ width: "100%", height: "100%", objectFit: "cover" }} alt="" /> : "🤖"}
                </div>
              )}
              <div style={{ maxWidth: "70%" }}>
                {msg.role === "agent" && msg.agentName && (
                  <div style={{ fontSize: 10, color: "#6B7280", marginBottom: 3 }}>{msg.agentName}</div>
                )}
                <div style={{
                  padding: "10px 14px", borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                  background: msg.role === "user" ? "#3B82F6" : "#fff",
                  color: msg.role === "user" ? "#fff" : "#1F2937",
                  fontSize: 13, lineHeight: 1.5,
                  borderLeft: msg.role === "agent" ? "3px solid rgba(59,130,246,0.3)" : "none",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
                  whiteSpace: "pre-wrap",
                }}>
                  {msg.text || (msg.streaming ? (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, color: "#6B7280" }}>
                      <Loader2 size={14} className="spin" /> KOGO is thinking…
                    </span>
                  ) : "")}
                </div>

                {/* File chips (file_datas) — shown below message bubble */}
                {msg.fileDatas && msg.fileDatas.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                    {msg.fileDatas.map((f, i) => (
                      <a
                        key={i}
                        href={f.url || "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: "inline-flex", alignItems: "center", gap: 4,
                          padding: "4px 10px", borderRadius: 6,
                          background: "#F3F4F6", border: "1px solid #E5E7EB",
                          fontSize: 12, color: "#374151", textDecoration: "none",
                        }}
                      >
                        <Paperclip size={11} />
                        {f.name}
                      </a>
                    ))}
                  </div>
                )}

                {/* Card data — rendered as cards below the message */}
                {msg.cardData && msg.cardData.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                    {msg.cardData.map((card, i) => (
                      <div
                        key={i}
                        style={{
                          background: "#fff", border: "1px solid #E5E7EB", borderRadius: 8,
                          padding: "10px 12px", boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
                        }}
                      >
                        {card.image && (
                          <img src={card.image} alt="" style={{ width: "100%", borderRadius: 4, marginBottom: 6, objectFit: "cover", maxHeight: 120 }} />
                        )}
                        {card.title && <div style={{ fontWeight: 600, fontSize: 13, color: "#111827" }}>{card.title}</div>}
                        {card.description && <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>{card.description}</div>}
                        {card.url && (
                          <a href={card.url} target="_blank" rel="noopener noreferrer"
                            style={{ display: "inline-flex", alignItems: "center", gap: 4, marginTop: 6, fontSize: 12, color: "#3B82F6", textDecoration: "none" }}>
                            Open <ExternalLink size={10} />
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Like/dislike buttons — shown on agent messages only */}
                {msg.role === "agent" && !msg.streaming && (
                  <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                    <button
                      onClick={() => setMessages(prev => prev.map(m => m.id === msg.id ? { ...m, likeStatus: m.likeStatus === "liked" ? null : "liked" } : m))}
                      style={{
                        background: "none", border: "none", cursor: "pointer", padding: "2px 6px", borderRadius: 4,
                        color: msg.likeStatus === "liked" ? "#16A34A" : "#9CA3AF",
                      }}
                      title="Like"
                    >
                      <ThumbsUp size={13} />
                    </button>
                    <button
                      onClick={() => setMessages(prev => prev.map(m => m.id === msg.id ? { ...m, likeStatus: m.likeStatus === "disliked" ? null : "disliked" } : m))}
                      style={{
                        background: "none", border: "none", cursor: "pointer", padding: "2px 6px", borderRadius: 4,
                        color: msg.likeStatus === "disliked" ? "#DC2626" : "#9CA3AF",
                      }}
                      title="Dislike"
                    >
                      <ThumbsDown size={13} />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Processing status — always visible while the agent is working */}
        {streaming && (
          <div style={{ padding: "8px 20px 0", background: "#fff", fontSize: 11.5, color: "#6B7280", display: "flex", alignItems: "center", gap: 6 }}>
            <Loader2 size={12} className="spin" /> KOGO is thinking — this can take a few seconds…
          </div>
        )}

        {/* Input */}
        <div style={{ padding: streaming ? "8px 20px 12px" : "12px 20px", borderTop: streaming ? "none" : "1px solid #E5E7EB", background: "#fff", display: "flex", gap: 8 }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); } }}
            disabled={streaming}
            placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
            style={{ flex: 1, padding: "10px 12px", border: "1px solid #E5E7EB", borderRadius: 8, fontSize: 13, resize: "none", outline: "none", maxHeight: 120, fontFamily: "inherit" }}
            rows={1}
          />
          <button
            onClick={sendMsg}
            disabled={streaming || !input.trim()}
            style={{ padding: "10px 16px", background: streaming || !input.trim() ? "#E5E7EB" : "#3B82F6", color: streaming || !input.trim() ? "#9CA3AF" : "#fff", border: "none", borderRadius: 8, cursor: streaming ? "not-allowed" : "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
            title={streaming ? "KOGO is thinking…" : "Send"}
          >
            {streaming ? <Loader2 size={16} className="spin" /> : <Send size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}
