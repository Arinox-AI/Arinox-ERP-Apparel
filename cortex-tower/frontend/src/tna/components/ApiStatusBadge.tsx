export type ApiStatus = "checking" | "connected" | "offline";

export default function ApiStatusBadge({ status }: { status: ApiStatus }) {
  if (status === "connected") {
    return (
      <span className="badge badge-success" title="Backend reachable via the KOGO middleware">
        <span className="dot dot-green" />
        Connected
      </span>
    );
  }
  if (status === "offline") {
    return (
      <span className="badge badge-error" title="The KOGO middleware health check did not return this project">
        <span className="dot dot-red" />
        Backend offline
      </span>
    );
  }
  return (
    <span className="badge" title="Checking the backend connection">
      <span className="dot dot-muted" />
      Checking…
    </span>
  );
}
