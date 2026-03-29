import { useMemo, useState } from "react";

import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime, getRuntimeTone, getSourceTone } from "../utils";
import type { AssetPageProps } from "./shared";

export function AssetsPage({
  data,
  language,
  pbsInventoryByVmId,
  savingKey,
  t,
  onVmCriticalChange,
}: AssetPageProps) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "vm" | "ct">("all");
  const [protectedFilter, setProtectedFilter] = useState<"all" | "protected" | "unprotected">(
    "all",
  );

  const filteredAssets = useMemo(() => {
    return data.vms.filter((vm) => {
      const backup = pbsInventoryByVmId.get(vm.id);
      const protectedState = backup?.protected ?? vm.last_backup_at !== null;

      if (typeFilter !== "all" && vm.vm_type !== typeFilter) {
        return false;
      }

      if (protectedFilter === "protected" && !protectedState) {
        return false;
      }

      if (protectedFilter === "unprotected" && protectedState) {
        return false;
      }

      if (!query.trim()) {
        return true;
      }

      const normalized = query.trim().toLowerCase();
      return (
        vm.name.toLowerCase().includes(normalized) ||
        (vm.node_name ?? "").toLowerCase().includes(normalized) ||
        (vm.external_id ?? "").toLowerCase().includes(normalized)
      );
    });
  }, [data.vms, pbsInventoryByVmId, protectedFilter, query, typeFilter]);

  return (
    <div className="page-stack">
      <PageHeader title={t.nav.assets} description={t.assetsIntro} />

      <section className="filters-bar">
        <label className="field">
          <span>{t.search}</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>

        <label className="field">
          <span>{t.filterType}</span>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as "all" | "vm" | "ct")}>
            <option value="all">{t.all}</option>
            <option value="vm">VM</option>
            <option value="ct">CT</option>
          </select>
        </label>

        <label className="field">
          <span>{t.filterProtection}</span>
          <select
            value={protectedFilter}
            onChange={(event) =>
              setProtectedFilter(event.target.value as "all" | "protected" | "unprotected")
            }
          >
            <option value="all">{t.all}</option>
            <option value="protected">{t.filterProtected}</option>
            <option value="unprotected">{t.filterUnprotected}</option>
          </select>
        </label>
      </section>

      {filteredAssets.length === 0 ? (
        <EmptyState description={t.assetsEmptyDescription} title={t.emptyVms} />
      ) : (
        <DataTable>
          <table>
            <thead>
              <tr>
                <th>{t.vmName}</th>
                <th>{t.vmType}</th>
                <th>{t.vmSource}</th>
                <th>{t.vmNode}</th>
                <th>{t.vmRuntimeStatus}</th>
                <th>{t.vmProtected}</th>
                <th>{t.vmCritical}</th>
                <th>{t.vmSize}</th>
                <th>{t.vmLastBackup}</th>
              </tr>
            </thead>
            <tbody>
              {filteredAssets.map((vm) => {
                const backup = pbsInventoryByVmId.get(vm.id);
                const protectedState = backup?.protected ?? vm.last_backup_at !== null;
                const lastBackup = backup?.last_backup_at ?? vm.last_backup_at;

                return (
                  <tr key={vm.id}>
                    <td>{vm.name}</td>
                    <td>{vm.vm_type.toUpperCase()}</td>
                    <td>
                      <StatusBadge tone={getSourceTone(vm.source)}>
                        {t.source[vm.source]}
                      </StatusBadge>
                    </td>
                    <td>{vm.node_name ?? t.notAvailable}</td>
                    <td>
                      <StatusBadge tone={getRuntimeTone(vm.runtime_status)}>
                        {vm.runtime_status ?? t.notAvailable}
                      </StatusBadge>
                    </td>
                    <td>
                      <StatusBadge tone={protectedState ? "success" : "warning"}>
                        {protectedState ? t.protectedLabel : t.unprotectedLabel}
                      </StatusBadge>
                    </td>
                    <td>
                      <label className="checkbox-cell">
                        <input
                          checked={vm.critical}
                          disabled={savingKey === `vm-${vm.id}`}
                          onChange={(event) => onVmCriticalChange(vm.id, event.target.checked)}
                          type="checkbox"
                        />
                        <span>{vm.critical ? t.yes : t.no}</span>
                      </label>
                    </td>
                    <td>{vm.size_gb} GB</td>
                    <td>{formatDateTime(lastBackup, language, t.notAvailable)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </DataTable>
      )}
    </div>
  );
}
