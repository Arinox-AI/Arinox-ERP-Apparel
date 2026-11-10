import { WifiOff } from "lucide-react";
import type { ApiStatus } from "./ApiStatusBadge";

/**
 * Shows only when the middleware health check fails. If we already hold data we
 * keep showing it; otherwise pages fall back to a readable empty state. We never
 * fabricate data.
 */
export default function OfflineBanner({ status, hasData }: { status: ApiStatus; hasData: boolean }) {
  if (status !== "offline") return null;
  return (
    <div className="banner banner-error">
      <WifiOff size={16} className="banner-icon" />
      <div>
        <div className="banner-title">Backend offline</div>
        <div>
          The KOGO middleware did not return this project on the health check.
          {hasData ? " Showing the last data loaded this session." : " No data is available yet."}
        </div>
      </div>
    </div>
  );
}
