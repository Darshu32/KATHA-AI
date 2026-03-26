const pillars = [
  {
    title: "Design Graph First",
    description:
      "Every room, wall, object, and material starts as structured data so we can support editing, rendering, and estimation from one source."
  },
  {
    title: "2D + 3D Sync",
    description:
      "The MVP is shaped around shared object IDs, making it possible to click a visual element and trace it back to a canonical design node."
  },
  {
    title: "Estimate Ready",
    description:
      "We are planning quantity and material workflows from day one instead of trying to infer them later from images."
  }
];

const modules = [
  "Prompt Studio",
  "Project Dashboard",
  "2D Render Panel",
  "3D Scene Viewer",
  "Selection Inspector",
  "Estimate Panel"
];

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-10 px-6 py-10 lg:px-10">
      <section className="grid gap-6 rounded-[2rem] border border-black/10 bg-white/65 p-8 shadow-panel backdrop-blur lg:grid-cols-[1.5fr_1fr]">
        <div className="space-y-6">
          <span className="inline-flex rounded-full border border-clay/30 bg-clay/10 px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] text-clay">
            KATHA AI MVP
          </span>
          <div className="space-y-4">
            <h1 className="max-w-3xl font-display text-5xl leading-tight text-ink md:text-6xl">
              Architecture-aware design generation with a real system behind it.
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-ink/75">
              This foundation is built for a product that can reason about layout,
              style, synchronized visualization, and measurable estimates instead
              of stopping at beautiful images.
            </p>
          </div>
        </div>

        <div className="rounded-[1.75rem] bg-ink p-6 text-white">
          <p className="text-sm uppercase tracking-[0.18em] text-white/60">
            Initial build focus
          </p>
          <div className="mt-6 space-y-4">
            {modules.map((module) => (
              <div
                key={module}
                className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3"
              >
                {module}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-3">
        {pillars.map((pillar) => (
          <article
            key={pillar.title}
            className="rounded-[1.5rem] border border-black/10 bg-sand p-6 shadow-panel"
          >
            <h2 className="font-display text-2xl text-ink">{pillar.title}</h2>
            <p className="mt-4 leading-7 text-ink/75">{pillar.description}</p>
          </article>
        ))}
      </section>

      <section className="grid gap-6 rounded-[2rem] border border-black/10 bg-white/70 p-8 shadow-panel lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <p className="text-sm uppercase tracking-[0.18em] text-sage">
            Current status
          </p>
          <h2 className="mt-3 font-display text-4xl text-ink">
            Project foundation is ready for feature work.
          </h2>
          <p className="mt-4 max-w-2xl leading-8 text-ink/75">
            The next steps are wiring prompt intake to the backend, persisting
            project versions, and introducing the first real design graph
            generation flow.
          </p>
        </div>

        <div className="rounded-[1.5rem] bg-mist p-6">
          <p className="text-sm uppercase tracking-[0.18em] text-clay">
            MVP sequence
          </p>
          <ol className="mt-4 space-y-4 pl-5 text-ink/80">
            <li>Capture prompt and project metadata.</li>
            <li>Generate a typed design graph draft.</li>
            <li>Expose project versions through the API.</li>
            <li>Attach 2D, 3D, and estimate placeholders to each version.</li>
          </ol>
        </div>
      </section>
    </main>
  );
}

