/**
 * TruvBrain — Productivity-Friend Dashboard Component (TypeScript wrapper)
 * =========================================================================
 * Drop this file into: TruvBrain/components/productivity/ProductivityFriendDashboard.tsx
 *
 * This is the TypeScript re-export of the JSX dashboard component.
 * It adds proper typing and ensures compatibility with Next.js App Router.
 *
 * The underlying component lives in:
 *   Productivity-Friend/productivity-friend-dashboard.jsx
 * Copy that file to:
 *   TruvBrain/components/productivity/ProductivityFriendDashboard.jsx
 * (or .tsx if you rename — the component is self-contained)
 */

"use client";

// Option A: Copy productivity-friend-dashboard.jsx alongside this file
// and import directly:
// import ProductivityFriendDashboard from "./productivity-friend-dashboard";

// Option B: If the JSX is in a separate package or path, adjust below.
// For now we re-export with type annotation:

interface Props {
  /** Base URL of the running api_server.py — default: http://localhost:8000 */
  apiBaseUrl?: string;
}

// Lazy-load to avoid SSR issues (dashboard uses browser APIs)
import dynamic from "next/dynamic";

const Dashboard = dynamic(
  () => import("./productivity-friend-dashboard"),
  {
    ssr: false,
    loading: () => (
      <div
        style={{
          background: "#080b0e",
          color: "#f5a623",
          fontFamily: "'IBM Plex Mono', monospace",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          fontSize: 13,
          letterSpacing: "0.15em",
        }}
      >
        ◈ PRODUCTIVITY-FRIEND LOADING…
      </div>
    ),
  }
);

export default function ProductivityFriendDashboard({ apiBaseUrl }: Props) {
  return <Dashboard apiBaseUrl={apiBaseUrl} />;
}
