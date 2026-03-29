import type { ReactNode } from "react";

import { StatusBadge } from "./StatusBadge";

interface StatCardProps {
  label: string;
  value: ReactNode;
  hint?: string;
  badge?: string;
  tone?: "neutral" | "success" | "danger" | "warning" | "info";
}

export function StatCard({ label, value, hint, badge, tone = "neutral" }: StatCardProps) {
  return (
    <article className="stat-card">
      <div className="stat-card-top">
        <p className="stat-label">{label}</p>
        {badge ? <StatusBadge tone={tone}>{badge}</StatusBadge> : null}
      </div>
      <p className="stat-value">{value}</p>
      {hint ? <p className="stat-hint">{hint}</p> : null}
    </article>
  );
}
