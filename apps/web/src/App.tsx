import { useMemo, useState } from "react";
import { Route, Routes } from "react-router-dom";

import { getExternalBackupPreview } from "./api";
import { AppShell } from "./components/AppShell";
import { ConfirmModal } from "./components/ConfirmModal";
import { ErrorBanner } from "./components/ErrorBanner";
import { LoadingBlock } from "./components/LoadingBlock";
import { PrepareDiskModal } from "./components/PrepareDiskModal";
import { useAppData } from "./hooks/useAppData";
import { translations, type Language } from "./i18n";
import { ActivityPage } from "./pages/ActivityPage";
import { AssetsPage } from "./pages/AssetsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DisksPage } from "./pages/DisksPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { PlanningPage } from "./pages/PlanningPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { DiskActionRequest, DiskPreparationSubmitPayload } from "./pages/shared";
import type { ExternalDisk } from "./types";
import { getLatestStatusLabel } from "./utils";

interface ConfirmState {
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  tone: "danger" | "warning" | "info";
  onConfirm: () => void;
}

export default function App() {
  const [language, setLanguage] = useState<Language>("fr");
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [preparationDisk, setPreparationDisk] = useState<ExternalDisk | null>(null);

  const {
    data,
    loading,
    error,
    bannerError,
    syncMessage,
    savingKey,
    proxmoxSyncing,
    pbsSyncing,
    pbsInventoryByVmId,
    load,
    clearBannerError,
    clearSyncMessage,
    mutateVmCritical,
    mutateDisk,
    runProxmoxSync,
    runPBSSync,
    startExternalBackup,
    startDiskPreparation,
  } = useAppData();

  const t = translations[language];

  const latestBackupLabel = useMemo(() => {
    return data ? getLatestStatusLabel(data.overview.latest_backup_status, t) : t.status.unknown;
  }, [data, t]);

  function openConfirm(nextState: ConfirmState) {
    setConfirmState(nextState);
  }

  function closeConfirm() {
    setConfirmState(null);
  }

  function closePreparationModal() {
    setPreparationDisk(null);
  }

  function handleDiskToggleRequest(request: DiskActionRequest) {
    const descriptors = {
      trusted: {
        title: t.confirmTrustedTitle,
        description: request.value ? t.confirmTrustedEnable : t.confirmTrustedDisable,
      },
      dedicated_backup_disk: {
        title: t.confirmDedicatedTitle,
        description: request.value ? t.confirmDedicatedEnable : t.confirmDedicatedDisable,
      },
      allow_existing_data: {
        title: t.confirmExistingDataTitle,
        description: request.value ? t.confirmExistingDataEnable : t.confirmExistingDataDisable,
      },
    } as const;

    const descriptor = descriptors[request.field];

    openConfirm({
      title: descriptor.title,
      description: `${request.disk.display_name}: ${descriptor.description}`,
      confirmLabel: t.confirm,
      cancelLabel: t.cancel,
      tone: "warning",
      onConfirm: () => {
        if (request.field === "trusted") {
          void mutateDisk(request.disk.id, { trusted: request.value });
        } else if (request.field === "dedicated_backup_disk") {
          void mutateDisk(request.disk.id, { dedicated_backup_disk: request.value });
        } else {
          void mutateDisk(request.disk.id, { allow_existing_data: request.value });
        }
        closeConfirm();
      },
    });
  }

  function handleProxmoxSyncRequest() {
    openConfirm({
      title: t.confirmSyncInventoryTitle,
      description: t.confirmSyncInventoryDescription,
      confirmLabel: t.proxmoxSync,
      cancelLabel: t.cancel,
      tone: "info",
      onConfirm: () => {
        void runProxmoxSync(t.proxmoxSyncSummary);
        closeConfirm();
      },
    });
  }

  function handlePBSSyncRequest() {
    openConfirm({
      title: t.confirmSyncBackupsTitle,
      description: t.confirmSyncBackupsDescription,
      confirmLabel: t.pbsSync,
      cancelLabel: t.cancel,
      tone: "info",
      onConfirm: () => {
        void runPBSSync(t.pbsSyncSummary);
        closeConfirm();
      },
    });
  }

  async function handleExternalBackupRequest(disk: ExternalDisk) {
    if (!disk.trusted) {
      openConfirm({
        title: t.confirmExternalBackupTitle,
        description: t.externalBackupBlockedUntrusted,
        confirmLabel: t.dismiss,
        cancelLabel: t.cancel,
        tone: "warning",
        onConfirm: closeConfirm,
      });
      return;
    }

    if (!disk.connected) {
      openConfirm({
        title: t.confirmExternalBackupTitle,
        description: t.externalBackupBlockedDisconnected,
        confirmLabel: t.dismiss,
        cancelLabel: t.cancel,
        tone: "warning",
        onConfirm: closeConfirm,
      });
      return;
    }

    if (!disk.dedicated_backup_disk && !disk.allow_existing_data) {
      openConfirm({
        title: t.confirmExternalBackupTitle,
        description: t.externalBackupBlockedMode,
        confirmLabel: t.dismiss,
        cancelLabel: t.cancel,
        tone: "warning",
        onConfirm: closeConfirm,
      });
      return;
    }

    try {
      const preview = await getExternalBackupPreview(disk.id);
      const modeLabel =
        preview.mode === "dedicated"
          ? t.externalBackupDedicatedMode
          : t.externalBackupCoexistenceMode;
      const preserveText = preview.preserves_existing_data
        ? t.externalBackupPreservesData
        : t.externalBackupUsesDedicatedPath;

      openConfirm({
        title: t.confirmExternalBackupTitle,
        description: [
          `${t.confirmExternalBackupDescription}`,
          `${t.diskName}: ${disk.display_name}`,
          `${t.externalBackupMode}: ${modeLabel}`,
          `${t.externalBackupTargetPath}: ${preview.target_path}`,
          `${t.externalBackupPBSHandoff}`,
          `${t.externalBackupPBSExclusive}`,
          preserveText,
        ].join(" "),
        confirmLabel: t.externalBackupAction,
        cancelLabel: t.cancel,
        tone: "info",
        onConfirm: () => {
          void startExternalBackup(disk.id, t.externalBackupSummary);
          closeConfirm();
        },
      });
    } catch (previewError) {
      openConfirm({
        title: t.confirmExternalBackupTitle,
        description: previewError instanceof Error ? previewError.message : t.error,
        confirmLabel: t.dismiss,
        cancelLabel: t.cancel,
        tone: "warning",
        onConfirm: closeConfirm,
      });
    }
  }

  function handleDiskPreparationRequest(disk: ExternalDisk) {
    if (!disk.connected) {
      openConfirm({
        title: t.prepareDiskTitle,
        description: t.prepareDiskBlockedDisconnected,
        confirmLabel: t.dismiss,
        cancelLabel: t.cancel,
        tone: "warning",
        onConfirm: closeConfirm,
      });
      return;
    }

    setPreparationDisk(disk);
  }

  async function handleDiskPreparationSubmit(payload: DiskPreparationSubmitPayload) {
    if (preparationDisk === null) {
      return;
    }

    const run = await startDiskPreparation(
      preparationDisk.id,
      {
        mode: payload.mode,
        mount_base_path: payload.mountBasePath,
        confirm_destructive: payload.confirmDestructive,
      },
      t.prepareDiskSummary,
    );
    if (run) {
      closePreparationModal();
    }
  }

  if (loading) {
    return (
      <div className="centered-shell">
        <LoadingBlock label={t.loading} />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="centered-shell">
        <section className="panel-card panel-narrow">
          <h1 className="page-title">{t.error}</h1>
          {error ? <ErrorBanner dismissLabel={t.dismiss} message={error} /> : null}
          <button className="action-button" onClick={() => void load()} type="button">
            {t.retry}
          </button>
        </section>
      </div>
    );
  }

  return (
    <>
      <AppShell language={language} onLanguageChange={setLanguage} t={t}>
        {bannerError ? (
          <ErrorBanner
            dismissLabel={t.dismiss}
            message={bannerError}
            onDismiss={clearBannerError}
          />
        ) : null}

        {syncMessage ? (
          <ErrorBanner
            dismissLabel={t.dismiss}
            message={syncMessage}
            onDismiss={clearSyncMessage}
            tone="info"
          />
        ) : null}

        <Routes>
          <Route
            element={<DashboardPage data={data} latestBackupLabel={latestBackupLabel} t={t} language={language} />}
            path="/"
          />
          <Route
            element={
              <AssetsPage
                data={data}
                language={language}
                onVmCriticalChange={(vmId, critical) => void mutateVmCritical(vmId, critical)}
                pbsInventoryByVmId={pbsInventoryByVmId}
                savingKey={savingKey}
                t={t}
              />
            }
            path="/assets"
          />
          <Route
            element={
              <DisksPage
                data={data}
                language={language}
                onDiskFieldChange={(diskId, payload) => void mutateDisk(diskId, payload)}
                onExternalBackupRequest={(disk) => void handleExternalBackupRequest(disk)}
                onDiskPreparationRequest={handleDiskPreparationRequest}
                onDiskToggleRequest={handleDiskToggleRequest}
                savingKey={savingKey}
                t={t}
              />
            }
            path="/disks"
          />
          <Route element={<PlanningPage data={data} language={language} t={t} />} path="/planning" />
          <Route
            element={
              <IntegrationsPage
                data={data}
                language={language}
                onPBSSyncRequest={handlePBSSyncRequest}
                onProxmoxSyncRequest={handleProxmoxSyncRequest}
                pbsSyncing={pbsSyncing}
                proxmoxSyncing={proxmoxSyncing}
                t={t}
              />
            }
            path="/integrations"
          />
          <Route
            element={
              <ActivityPage
                data={data}
                externalBackupRuns={data.externalBackupRuns}
                language={language}
                t={t}
              />
            }
            path="/activity"
          />
          <Route element={<SettingsPage t={t} />} path="/settings" />
        </Routes>
      </AppShell>

      <ConfirmModal
        cancelLabel={confirmState?.cancelLabel ?? t.cancel}
        confirmLabel={confirmState?.confirmLabel ?? t.confirm}
        description={confirmState?.description ?? ""}
        onCancel={closeConfirm}
        onConfirm={() => confirmState?.onConfirm()}
        open={confirmState !== null}
        title={confirmState?.title ?? ""}
        tone={confirmState?.tone ?? "warning"}
      />
      <PrepareDiskModal
        disk={preparationDisk}
        onCancel={closePreparationModal}
        onSubmit={handleDiskPreparationSubmit}
        open={preparationDisk !== null}
        submitting={Boolean(preparationDisk && savingKey === `disk-prep-${preparationDisk.id}`)}
        t={t}
      />
    </>
  );
}
