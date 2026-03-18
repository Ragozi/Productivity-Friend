/**
 * TruvBrain — Productivity-Friend Panel
 * ======================================
 * Drop this file into: TruvBrain/app/(internal)/productivity/page.tsx
 *
 * Then add a nav link in components/internal/InternalSidebar.tsx — see
 * sidebar-snippet.txt in this same folder for the exact lines to add.
 *
 * Env var to set in TruvBrain/.env.local:
 *   NEXT_PUBLIC_PRODUCTIVITY_FRIEND_URL=http://localhost:8000
 *
 * The api_server.py must be running on the same machine (or accessible URL).
 */

import ProductivityFriendDashboard from "@/components/productivity/ProductivityFriendDashboard";

export default function ProductivityPage() {
  const apiUrl =
    process.env.NEXT_PUBLIC_PRODUCTIVITY_FRIEND_URL || "http://localhost:8000";

  return (
    <div className="h-full w-full">
      <ProductivityFriendDashboard apiBaseUrl={apiUrl} />
    </div>
  );
}
