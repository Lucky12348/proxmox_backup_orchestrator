import type { ReactNode } from "react";
import { StatusBadge } from "./StatusBadge";

interface StatCardProps {
  label: string;
  value: ReactNode;
  hint?: string;
  badge?: string;
  tone?: "neutral" | "success" | "danger" | "warning" | "info";
}

const toneValueClass: Record<string, string> = {
  success: "stat-value-success",
  danger:  "stat-value-danger",
  warning: "stat-value-warning",
  info:    "stat-value-accent",
  neutral: "",
};

export function StatCard({ label, value, hint, badge, tone = "neutral" }: StatCardProps) {
  return (
    <article className="stat-card">
      <div className="stat-card-top">
        <p className="stat-label">{label}</p>
        {badge ? <StatusBadge tone={tone}>{badge}</StatusBadge> : null}
      </div>
      <p className={`stat-value ${toneValueClass[tone] ?? ""}`}>{value}</p>
      {hint ? <p className="stat-hint">{hint}</p> : null}
    </article>
  );
}
