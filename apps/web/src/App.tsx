import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Route, Routes } from "react-router-dom";

import { getExternalBackupPreview, AUTH_EXPIRED_EVENT } from "./api";
import { AuthProvider, useAuth } from "./AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { AppShell } from "./components/AppShell";
import { ConfirmModal } from "./components/ConfirmModal";
import { ErrorBanner } from "./components/ErrorBanner";
import { LoadingBlock } from "./components/LoadingBlock";
import { useAppData } from "./hooks/useAppData";
import { translations, type Language } from "./i18n";
import { ActivityPage } from "./pages/ActivityPage";
import { AssetsPage } from "./pages/AssetsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DisksPage } from "./pages/DisksPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { PlanningPage } from "./pages/PlanningPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { DiskActionRequest } from "./pages/shared";
import type { ExternalDisk } from "./types";
import { getLatestStatusLabel } from "./utils";

interface ConfirmState {
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  tone: "danger" | "warning" | "info";
  onConfirm: () => void;
  extra?: ReactNode;
}

const LANGUAGE_STORAGE_KEY = "pbo:language";

function getStoredLanguage(): Language {
  const value = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  return value === "en" || value === "fr" ? value : "fr";
}

// Inner app — rendered only when authenticated
function AuthenticatedApp() {
  const { logout } = useAuth();
  const [language, setLanguage] = useState<Language>(() => getStoredLanguage());
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  // Read at confirm-time by handleExternalBackupRequest; a ref (not state) so
  // toggling the checkbox doesn't re-render/recreate the modal's onConfirm closure.
  const autoEjectAfterSuccessRef = useRef(true);

  // Listen for auth-expired events from api.ts
  useEffect(() => {
    const handler = () => logout();
    window.addEventListener(AUTH_EXPIRED_EVENT, handler);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handler);
  }, [logout]);

  const {
    data,
    loading,
    error,
    bannerError,
    syncMessage,
    isSaving,
    proxmoxSyncing,
    pbsSyncing,
    pbsInventoryByVmId,
    load,
    clearBannerError,
    clearSyncMessage,
    mutateAssetIgnore,
    mutateBackupJobSelection,
    mutateDisk,
    runProxmoxSync,
    runPBSSync,
    startExternalBackup,
    ejectDisk,
    cleanupActivityRuns,
  } = useAppData();

  const t = translations[language];

  function handleLanguageChange(nextLanguage: Language) {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, nextLanguage);
    setLanguage(nextLanguage);
  }

  const latestBackupLabel = useMemo(() => {
    return data ? getLatestStatusLabel(data.overview.latest_backup_status, t) : t.status.unknown;
  }, [data, t]);

  function openConfirm(nextState: ConfirmState) { setConfirmState(nextState); }
  function closeConfirm() { setConfirmState(null); }

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
    } as const;
    const descriptor = descriptors[request.field];
    openConfirm({
      title: descriptor.title,
      description: `${request.disk.display_name}: ${descriptor.description}`,
      confirmLabel: t.confirm,
      cancelLabel: t.cancel,
      tone: "warning",
      onConfirm: () => {
        if (request.field === "trusted") void mutateDisk(request.disk.id, { trusted: request.value });
        else if (request.field === "dedicated_backup_disk") void mutateDisk(request.disk.id, { dedicated_backup_disk: request.value });
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
      onConfirm: () => { void runProxmoxSync(t.proxmoxSyncSummary); closeConfirm(); },
    });
  }

  function handlePBSSyncRequest() {
    openConfirm({
      title: t.confirmSyncBackupsTitle,
      description: t.confirmSyncBackupsDescription,
      confirmLabel: t.pbsSync,
      cancelLabel: t.cancel,
      tone: "info",
      onConfirm: () => { void runPBSSync(t.pbsSyncSummary); closeConfirm(); },
    });
  }

  function handleActivityCleanupRequest() {
    openConfirm({
      title: t.activityCleanupTitle,
      description: t.activityCleanupDescription,
      confirmLabel: t.activityCleanupConfirm,
      cancelLabel: t.cancel,
      tone: "danger",
      onConfirm: () => { void cleanupActivityRuns(10, t.activityCleanupSummary); closeConfirm(); },
    });
  }

  async function handleExternalBackupRequest(disk: ExternalDisk) {
    if (!disk.trusted) {
      openConfirm({
        title: t.confirmExternalBackupTitle,
        description: t.externalBackupBlockedUntrusted,
        confirmLabel: t.dismiss, cancelLabel: t.cancel, tone: "warning",
        onConfirm: closeConfirm,
      });
      return;
    }
    if (!disk.connected) {
      openConfirm({
        title: t.confirmExternalBackupTitle,
        description: t.externalBackupBlockedDisconnected,
        confirmLabel: t.dismiss, cancelLabel: t.cancel, tone: "warning",
        onConfirm: closeConfirm,
      });
      return;
    }
    try {
      const preview = await getExternalBackupPreview(disk.id);
      const modeLabel = preview.mode === "dedicated" ? t.externalBackupDedicatedMode : t.externalBackupCoexistenceMode;
      const preserveText = preview.preserves_existing_data ? t.externalBackupPreservesData : t.externalBackupUsesDedicatedPath;
      const preparationWarning = disk.prepared_as_pbs_datastore ? t.externalBackupReuseWarning : t.externalBackupDestructiveWarning;
      const loopSizeText = preview.mode === "coexistence" && preview.loop_image_size_gb !== null
        ? `${t.externalBackupLoopSize}: ${preview.loop_image_size_gb} GiB.` : null;
      const loopWarningText = preview.loop_image_size_warning ? t.externalBackupLoopSizeWarning : null;
      autoEjectAfterSuccessRef.current = true;
      openConfirm({
        title: t.confirmExternalBackupTitle,
        description: [
          `${t.confirmExternalBackupDescription}`,
          `${t.diskName}: ${disk.display_name}`,
          `${t.externalBackupMode}: ${modeLabel}`,
          `${t.externalBackupTargetPath}: ${preview.target_path}`,
          `${t.externalBackupPBSHandoff}`,
          `${t.externalBackupPBSExclusive}`,
          preparationWarning, preserveText, loopSizeText, loopWarningText,
        ].filter(Boolean).join(" "),
        confirmLabel: t.externalBackupAction,
        cancelLabel: t.cancel,
        tone: "info",
        extra: (
          <label className="checkbox-field">
            <input
              defaultChecked
              onChange={(event) => { autoEjectAfterSuccessRef.current = event.target.checked; }}
              type="checkbox"
            />
            <span>{t.externalBackupAutoEject}</span>
          </label>
        ),
        onConfirm: () => {
          void startExternalBackup(disk.id, t.externalBackupSummary, autoEjectAfterSuccessRef.current);
          closeConfirm();
        },
      });
    } catch (previewError) {
      openConfirm({
        title: t.confirmExternalBackupTitle,
        description: previewError instanceof Error ? previewError.message : t.error,
        confirmLabel: t.dismiss, cancelLabel: t.cancel, tone: "warning",
        onConfirm: closeConfirm,
      });
    }
  }

  function handleDiskEjectRequest(disk: ExternalDisk) {
    openConfirm({
      title: t.ejectDiskTitle,
      description: [`${t.diskName}: ${disk.display_name}`, t.ejectDiskConfirmation].join(" "),
      confirmLabel: t.ejectDiskAction,
      cancelLabel: t.cancel,
      tone: "warning",
      onConfirm: () => { void ejectDisk(disk.id, t.ejectDiskSuccess); closeConfirm(); },
    });
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
      <AppShell language={language} onLanguageChange={handleLanguageChange} t={t}>
        {bannerError ? (
          <ErrorBanner dismissLabel={t.dismiss} message={bannerError} onDismiss={clearBannerError} />
        ) : null}
        {syncMessage ? (
          <ErrorBanner dismissLabel={t.dismiss} message={syncMessage} onDismiss={clearSyncMessage} tone="info" />
        ) : null}

        <Routes>
          <Route element={<DashboardPage data={data} latestBackupLabel={latestBackupLabel} t={t} language={language} />} path="/" />
          <Route
            element={
              <AssetsPage
                data={data} language={language}
                onAssetIgnoreChange={(vm, ignored) => void mutateAssetIgnore(vm, ignored)}
                onBackupJobSelectionChange={(jobId, vmids) => void mutateBackupJobSelection(jobId, vmids)}
                pbsInventoryByVmId={pbsInventoryByVmId}
                isSaving={isSaving} t={t}
              />
            }
            path="/assets"
          />
          <Route
            element={
              <DisksPage
                data={data} language={language}
                onDiskFieldChange={(diskId, payload) => void mutateDisk(diskId, payload)}
                onDiskEjectRequest={handleDiskEjectRequest}
                onExternalBackupRequest={(disk) => void handleExternalBackupRequest(disk)}
                onDiskToggleRequest={handleDiskToggleRequest}
                isSaving={isSaving} t={t}
              />
            }
            path="/disks"
          />
          <Route element={<PlanningPage data={data} language={language} t={t} />} path="/planning" />
          <Route
            element={
              <IntegrationsPage
                data={data} language={language}
                onPBSSyncRequest={handlePBSSyncRequest}
                onProxmoxSyncRequest={handleProxmoxSyncRequest}
                pbsSyncing={pbsSyncing} proxmoxSyncing={proxmoxSyncing} t={t}
              />
            }
            path="/integrations"
          />
          <Route
            element={
              <ActivityPage
                data={data}
                cleanupSaving={isSaving("activity-cleanup")}
                externalBackupRuns={data.externalBackupRuns}
                language={language}
                onCleanupOldRunsRequest={handleActivityCleanupRequest}
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
        extra={confirmState?.extra}
        onCancel={closeConfirm}
        onConfirm={() => confirmState?.onConfirm()}
        open={confirmState !== null}
        title={confirmState?.title ?? ""}
        tone={confirmState?.tone ?? "warning"}
      />
    </>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppInner />
    </AuthProvider>
  );
}

function AppInner() {
  const { isAuthenticated } = useAuth();
  // We need t for LoginPage — use default language here
  const t = translations["fr"];

  if (!isAuthenticated) {
    return <LoginPage t={t} />;
  }

  return <AuthenticatedApp />;
}
