import type { ReactNode } from "react";

export default function EmptyState({ icon, title, message }: { icon?: ReactNode; title: string; message?: string }) {
  return (
    <div className="empty">
      {icon}
      <div className="empty-title">{title}</div>
      {message && <div style={{ fontSize: 13, maxWidth: 460 }}>{message}</div>}
    </div>
  );
}
