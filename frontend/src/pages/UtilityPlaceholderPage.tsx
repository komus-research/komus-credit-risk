export function UtilityPlaceholderPage({ title }: { title: string }) {
  return <main className="workspace utility-placeholder-workspace">
    <section className="panel utility-placeholder-panel">
      <h1>{title}</h1>
      <p>Раздел появится позже.</p>
    </section>
  </main>
}
