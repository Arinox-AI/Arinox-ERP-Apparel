export interface ToastItem {
  id: string;
  kind: "success" | "error" | "info";
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}

export default function ToastStack({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-wrap">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`}>
          <span className="toast-msg">{t.message}</span>
          {t.actionLabel && t.onAction && (
            <button
              className="toast-action"
              onClick={() => { t.onAction!(); onDismiss(t.id); }}
            >
              {t.actionLabel}
            </button>
          )}
          <button className="toast-action" onClick={() => onDismiss(t.id)}>✕</button>
        </div>
      ))}
    </div>
  );
}
