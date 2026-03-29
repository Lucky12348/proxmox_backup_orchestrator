import type { ReactNode } from "react";

type StatusTone = "neutral" | "success" | "danger" | "warning" | "info";

interface StatusBadgeProps {
  children: ReactNode;
  tone?: StatusTone;
}

export function StatusBadge({ children, tone = "neutral" }: StatusBadgeProps) {
  return <span className={`status-badge status-${tone}`}>{children}</span>;
}
