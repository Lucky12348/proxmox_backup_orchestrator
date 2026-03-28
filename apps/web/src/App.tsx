const cards = [
  {
    title: "System Coverage",
    description: "Placeholder for hosts, VMs, and backup scope visibility.",
  },
  {
    title: "External Disks",
    description: "Placeholder for removable disk detection and attachment status.",
  },
  {
    title: "Backup History",
    description: "Placeholder for recent backup runs, outcomes, and retention.",
  },
];

export default function App() {
  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h1>Proxmox Backup Orchestrator</h1>
          <p className="subtitle">
            Minimal frontend scaffold for monitoring coverage, removable media,
            and backup execution.
          </p>
        </div>

        <label className="language-select">
          <span>Language</span>
          <select defaultValue="en" aria-label="Language selection">
            <option value="fr">FR</option>
            <option value="en">EN</option>
          </select>
        </label>
      </section>

      <section className="card-grid">
        {cards.map((card) => (
          <article className="card" key={card.title}>
            <h2>{card.title}</h2>
            <p>{card.description}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
