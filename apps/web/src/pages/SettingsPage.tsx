import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import type { SettingsPageProps } from "./shared";

export function SettingsPage({ t }: SettingsPageProps) {
  return (
    <div className="page-stack">
      <PageHeader title={t.nav.settings} description={t.settingsIntro} />
      <section className="panel-card">
        <EmptyState description={t.settingsDescription} title={t.settingsPlaceholder} />
      </section>
    </div>
  );
}
