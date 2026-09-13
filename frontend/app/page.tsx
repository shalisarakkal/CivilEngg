export default function Home() {
  return (
    <main className="workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">Civil engineering intelligence</p>
          <h1>Project workspace</h1>
        </div>
        <span className="status">Phase 1 scaffold</span>
      </header>

      <section className="intro" aria-labelledby="intro-title">
        <div>
          <p className="eyebrow">Local-first project setup</p>
          <h2 id="intro-title">Turn plans into decisions.</h2>
          <p className="lede">
            Upload a plan, build a traceable site model, and validate engineering measurements from one workspace.
          </p>
        </div>
        <div className="next-step">
          <span className="step-number">01</span>
          <div>
            <strong>Next workflow</strong>
            <p>Create a project and upload your first source file.</p>
          </div>
        </div>
      </section>

      <section className="cards" aria-label="Workspace modules">
        <article className="module-card">
          <span className="card-index">01</span>
          <h3>Projects</h3>
          <p>Organize clients, source files, revisions, and calculations.</p>
          <span className="card-state">Coming next</span>
        </article>
        <article className="module-card active">
          <span className="card-index">02</span>
          <h3>Source files</h3>
          <p>PDF, DXF, CSV, and TXT ingestion with visible processing status.</p>
          <span className="card-state">Scaffold ready</span>
        </article>
        <article className="module-card">
          <span className="card-index">03</span>
          <h3>Measurements</h3>
          <p>Distance, elevation, slope, and area calculations with provenance.</p>
          <span className="card-state">Planned</span>
        </article>
      </section>
    </main>
  );
}
