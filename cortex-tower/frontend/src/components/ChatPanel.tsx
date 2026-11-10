import { Sparkles } from "lucide-react";
import { Drawer } from "../ui";
import AgentChat from "./AgentChat";

export function ChatPanel({ onClose, initialInput }: { onClose: () => void; initialInput?: string }) {
  return (
    <Drawer
      wide
      onClose={onClose}
      title={<span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><Sparkles size={15} /> Ask KOGO</span>}
      sub="Chat with the KOGO agent — threads and history, live."
    >
      <div style={{ height: "calc(100vh - 150px)", margin: -20, overflow: "hidden" }}>
        <AgentChat initialInput={initialInput} />
      </div>
    </Drawer>
  );
}
