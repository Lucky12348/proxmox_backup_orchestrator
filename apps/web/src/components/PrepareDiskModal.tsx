import { useEffect, useState } from "react";

import type { TranslationDictionary } from "../i18n";
import type { ExternalDisk } from "../types";
import type { DiskPreparationSubmitPayload } from "../pages/shared";

interface PrepareDiskModalProps {
  open: boolean;
  disk: ExternalDisk | null;
  t: TranslationDictionary;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (payload: DiskPreparationSubmitPayload) => void | Promise<void>;
}

export function PrepareDiskModal({
  open,
  disk,
  t,
  submitting,
  onCancel,
  onSubmit,
}: PrepareDiskModalProps) {
  const [mode, setMode] = useState<"preserve_existing_data" | "dedicated_backup">(
    "preserve_existing_data",
  );
  const [mountBasePath, setMountBasePath] = useState("");
  const [confirmDestructive, setConfirmDestructive] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }

    setMode("preserve_existing_data");
    setMountBasePath("");
    setConfirmDestructive(false);
  }, [open, disk?.id]);

  if (!open || disk === null) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <section
        className="modal-card"
        role="dialog"
        aria-modal="true"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <p className="modal-tone modal-tone-info">{t.prepareDiskTitle}</p>
          <button aria-label={t.cancel} className="icon-button" onClick={onCancel} type="button">
            x
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-description">{t.prepareDiskDescription}</p>
          <div className="summary-list">
            <div className="summary-row">
              <span>{t.diskName}</span>
              <strong>{disk.display_name}</strong>
            </div>
            <div className="summary-row">
              <span>{t.diskSerial}</span>
              <strong>{disk.serial_number}</strong>
            </div>
            <div className="summary-row">
              <span>{t.diskFilesystem}</span>
              <strong>{disk.filesystem_type ?? t.notAvailable}</strong>
            </div>
          </div>

          <div className="choice-grid">
            <label className="choice-card">
              <input
                checked={mode === "preserve_existing_data"}
                name="prep-mode"
                onChange={() => setMode("preserve_existing_data")}
                type="radio"
              />
              <div>
                <strong>{t.prepareDiskPreserve}</strong>
                <p>{t.prepareDiskPreserveDescription}</p>
              </div>
            </label>

            <label className="choice-card choice-card-danger">
              <input
                checked={mode === "dedicated_backup"}
                name="prep-mode"
                onChange={() => setMode("dedicated_backup")}
                type="radio"
              />
              <div>
                <strong>{t.prepareDiskDedicated}</strong>
                <p>{t.prepareDiskDedicatedDescription}</p>
              </div>
            </label>
          </div>

          <label className="field">
            <span>{t.prepareDiskMountBasePath}</span>
            <input
              onChange={(event) => setMountBasePath(event.target.value)}
              placeholder="/mnt/pbo"
              value={mountBasePath}
            />
          </label>

          {mode === "dedicated_backup" ? (
            <label className="checkbox-cell destructive-check">
              <input
                checked={confirmDestructive}
                onChange={(event) => setConfirmDestructive(event.target.checked)}
                type="checkbox"
              />
              <span>{t.prepareDiskConfirmDestructive}</span>
            </label>
          ) : null}
        </div>

        <div className="modal-actions">
          <button className="ghost-button" onClick={onCancel} type="button">
            {t.cancel}
          </button>
          <button
            className="action-button"
            disabled={submitting || (mode === "dedicated_backup" && !confirmDestructive)}
            onClick={() =>
              void
              onSubmit({
                mode,
                mountBasePath: mountBasePath.trim() || undefined,
                confirmDestructive,
              })
            }
            type="button"
          >
            {submitting ? t.preparingDisk : t.prepareDiskAction}
          </button>
        </div>
      </section>
    </div>
  );
}
