import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime } from "../utils";
import type { IntegrationsPageProps } from "./shared";

export function IntegrationsPage({
  data,
  language,
  proxmoxSyncing,
  pbsSyncing,
  t,
  onProxmoxSyncRequest,
  onPBSSyncRequest,
}: IntegrationsPageProps) {
  return (
    <div className="page-stack">
      <PageHeader title={t.nav.integrations} description={t.integrationsIntro} />

      <section className="integration-grid">
        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.proxmoxConnection}</h2>
            <button className="action-button" disabled={proxmoxSyncing} onClick={onProxmoxSyncRequest} type="button">
              {proxmoxSyncing ? t.proxmoxSyncing : t.proxmoxSync}
            </button>
          </div>
          <div className="integration-details">
            <div className="summary-row">
              <span>{t.proxmoxStatus}</span>
              <StatusBadge tone={data.proxmoxStatus.connected ? "success" : "danger"}>
                {data.proxmoxStatus.connected ? t.connected : t.disconnected}
              </StatusBadge>
            </div>
            <div className="summary-row">
              <span>{t.proxmoxNode}</span>
              <strong>{data.proxmoxStatus.node_name}</strong>
            </div>
            <div className="summary-row">
              <span>{t.proxmoxSsl}</span>
              <strong>{data.proxmoxStatus.verify_ssl ? t.yes : t.no}</strong>
            </div>
            <p className="integration-message">{data.proxmoxStatus.message}</p>
          </div>
        </article>

        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.pbsConnection}</h2>
            <button className="action-button" disabled={pbsSyncing} onClick={onPBSSyncRequest} type="button">
              {pbsSyncing ? t.pbsSyncing : t.pbsSync}
            </button>
          </div>
          <div className="integration-details">
            <div className="summary-row">
              <span>{t.pbsStatus}</span>
              <StatusBadge tone={data.pbsStatus.connected ? "success" : "danger"}>
                {data.pbsStatus.connected ? t.connected : t.disconnected}
              </StatusBadge>
            </div>
            <div className="summary-row">
              <span>{t.pbsDatastore}</span>
              <strong>{data.pbsStatus.datastore}</strong>
            </div>
            <div className="summary-row">
              <span>{t.pbsSsl}</span>
              <strong>{data.pbsStatus.verify_ssl ? t.yes : t.no}</strong>
            </div>
            <p className="integration-message">{data.pbsStatus.message}</p>
          </div>
        </article>

        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.agentStatus}</h2>
            <StatusBadge tone={data.agentStatus.connected ? "success" : "warning"}>
              {data.agentStatus.connected ? t.connected : t.degraded}
            </StatusBadge>
          </div>
          <div className="integration-details">
            <div className="summary-row">
              <span>{t.agentHostname}</span>
              <strong>{data.agentStatus.hostname ?? t.notAvailable}</strong>
            </div>
            <div className="summary-row">
              <span>{t.agentHeartbeat}</span>
              <strong>{formatDateTime(data.agentStatus.last_heartbeat_at, language, t.notAvailable)}</strong>
            </div>
            <div className="summary-row">
              <span>{t.agentReport}</span>
              <strong>{formatDateTime(data.agentStatus.last_report_at, language, t.notAvailable)}</strong>
            </div>
            <p className="integration-message">{t.agentDescription}</p>
          </div>
        </article>
      </section>
    </div>
  );
}
