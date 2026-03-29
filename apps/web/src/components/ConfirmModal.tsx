interface ConfirmModalProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  tone?: "danger" | "warning" | "info";
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel,
  tone = "warning",
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <section
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        className="modal-card"
        role="dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <p className={`modal-tone modal-tone-${tone}`} id="confirm-modal-title">
            {title}
          </p>
          <button aria-label={cancelLabel} className="icon-button" onClick={onCancel} type="button">
            x
          </button>
        </div>
        <p className="modal-description">{description}</p>
        <div className="modal-actions">
          <button className="ghost-button" onClick={onCancel} type="button">
            {cancelLabel}
          </button>
          <button className={`action-button action-${tone}`} onClick={onConfirm} type="button">
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
