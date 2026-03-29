import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatCard } from "../components/StatCard";
import type { PlanningPageProps } from "./shared";

export function PlanningPage({ data, t }: PlanningPageProps) {
  return (
    <div className="page-stack">
      <PageHeader title={t.nav.planning} description={t.planningIntro} />

      <section className="stats-grid stats-grid-compact">
        <StatCard label={t.planningCoverage} value={`${data.planningOverview.planning_coverage_percent}%`} />
        <StatCard label={t.planningTrustedDisks} value={data.planningOverview.trusted_disk_count} />
        <StatCard
          label={t.planningPlannedAssets}
          value={`${data.planningOverview.planned_vm_count} / ${data.planningOverview.plannable_vm_count}`}
        />
      </section>

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>{t.diskPlanningSummary}</h2>
        </div>
        {data.planningDisks.length === 0 ? (
          <EmptyState description={t.planningEmptyDescription} title={t.emptyPlanningDisks} />
        ) : (
          <DataTable>
            <table>
              <thead>
                <tr>
                  <th>{t.diskName}</th>
                  <th>{t.planningAvailableCapacity}</th>
                  <th>{t.planningTotalPlanned}</th>
                  <th>{t.planningPlannedVmCount}</th>
                  <th>{t.planningUnplannedVmCount}</th>
                  <th>{t.planningFitsAll}</th>
                </tr>
              </thead>
              <tbody>
                {data.planningDisks.map((disk) => (
                  <tr key={disk.disk_id}>
                    <td>{disk.display_name}</td>
                    <td>{disk.available_capacity_gb} GB</td>
                    <td>{disk.total_planned_gb} GB</td>
                    <td>{disk.planned_vm_count}</td>
                    <td>{disk.unplanned_vm_count}</td>
                    <td>{disk.fits_all ? t.yes : t.no}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
      </section>

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>{t.planningUnplannedAssets}</h2>
        </div>
        {data.unplannedAssets.length === 0 ? (
          <EmptyState title={t.emptyUnplannedAssets} />
        ) : (
          <DataTable>
            <table>
              <thead>
                <tr>
                  <th>{t.vmName}</th>
                  <th>{t.vmType}</th>
                  <th>{t.vmSize}</th>
                  <th>{t.vmCritical}</th>
                </tr>
              </thead>
              <tbody>
                {data.unplannedAssets.map((vm) => (
                  <tr key={vm.vm_id}>
                    <td>{vm.name}</td>
                    <td>{vm.vm_type.toUpperCase()}</td>
                    <td>{vm.size_gb} GB</td>
                    <td>{vm.critical ? t.yes : t.no}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
      </section>
    </div>
  );
}
