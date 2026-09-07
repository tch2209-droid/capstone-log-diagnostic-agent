import Link from "next/link";

type AppHeaderProps = {
  active: "review" | "orchestration";
  reviewerName: string;
  isAuthenticated: boolean;
  statusLabel: string;
  statusTone?: "live" | "demo";
};

export function AppHeader({
  active,
  reviewerName,
  isAuthenticated,
  statusLabel,
  statusTone = "live",
}: AppHeaderProps) {
  return (
    <header className="topbar">
      <Link className="brand-block" href="/" aria-label="SignalDesk home">
        <span className="brand-mark">S</span>
        <div><strong>SignalDesk</strong><span>Incident intelligence</span></div>
      </Link>

      <nav className="app-nav" aria-label="SignalDesk sections">
        <Link className={active === "review" ? "active" : ""} href="/">Review console</Link>
        <Link className={active === "orchestration" ? "active" : ""} href="/orchestration">Orchestration demo</Link>
      </nav>

      <div className="topbar-meta">
        <div className={`topbar-status status-${statusTone}`}>
          <span className="live-dot" />{statusLabel}
        </div>
        <div className="reviewer-chip" title={isAuthenticated ? "Authenticated reviewer" : "Local preview reviewer"}>
          <span>{reviewerName.slice(0, 1).toUpperCase()}</span>
          <div><strong>{reviewerName}</strong><small>{isAuthenticated ? "Verified reviewer" : "Local preview"}</small></div>
        </div>
      </div>
    </header>
  );
}
