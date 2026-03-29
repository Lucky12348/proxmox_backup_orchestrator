interface LoadingBlockProps {
  label: string;
}

export function LoadingBlock({ label }: LoadingBlockProps) {
  return (
    <div className="loading-block">
      <div className="loading-spinner" />
      <p>{label}</p>
    </div>
  );
}
