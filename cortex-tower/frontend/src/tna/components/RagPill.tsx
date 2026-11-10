import type { Rag } from "../types";

const LABEL: Record<Rag, string> = { red: "Red", amber: "Amber", green: "Green" };

export default function RagPill({ rag, label }: { rag: Rag | string; label?: string }) {
  const r = (rag === "red" || rag === "amber" || rag === "green") ? rag : "amber";
  return (
    <span className={`rag rag-${r}`} title={`RAG: ${r}`}>
      <span className={`dot dot-${r}`} />
      {label ?? LABEL[r as Rag]}
    </span>
  );
}
