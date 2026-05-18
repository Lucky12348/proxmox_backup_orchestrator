interface ErrorBannerProps {
  message: string;
  tone?: "error" | "info";
  dismissLabel?: string;
  onDismiss?: () => void;
}

export function ErrorBanner({
  message,
  tone = "error",
  dismissLabel = "Close",
  onDismiss,
}: ErrorBannerProps) {
  return (
    <section className={`banner ${tone === "info" ? "banner-info" : "banner-error"}`}>
      <p>{message}</p>
      {onDismiss ? (
        <button className="ghost-button" onClick={onDismiss} type="button" style={{ minHeight: 28, fontSize: 12 }}>
          {dismissLabel}
        </button>
      ) : null}
    </section>
  );
}
