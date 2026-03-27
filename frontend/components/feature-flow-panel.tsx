"use client";

import type { ArchitectureFeatureFlowResponse } from "../lib/api-client";

const FEATURE_LABELS: Record<string, string> = {
  initial_generation: "Initial generation",
  local_edit: "Local edit",
  theme_switch: "Theme switch",
  estimation: "Estimation",
};

interface FeatureFlowPanelProps {
  activeFeature: string;
  data: ArchitectureFeatureFlowResponse | null;
  isLoading: boolean;
  onSelectFeature: (feature: string) => void;
}

const FEATURE_OPTIONS = Object.keys(FEATURE_LABELS);

export default function FeatureFlowPanel({
  activeFeature,
  data,
  isLoading,
  onSelectFeature,
}: FeatureFlowPanelProps) {
  return (
    <section className="rounded-[1.75rem] border border-black/10 bg-white/70 p-6 shadow-panel">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.18em] text-clay">
            Feature Flow
          </p>
          <h2 className="mt-2 font-display text-3xl text-ink">
            End-to-end traceability
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-7 text-ink/65">
            Pick a product behavior and follow it from the frontend entrypoint
            through backend orchestration, persistence, and rendering.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {FEATURE_OPTIONS.map((feature) => {
            const isActive = activeFeature === feature;
            return (
              <button
                key={feature}
                type="button"
                onClick={() => onSelectFeature(feature)}
                className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-ink text-white"
                    : "bg-sand text-ink/70 hover:bg-mist"
                }`}
              >
                {FEATURE_LABELS[feature]}
              </button>
            );
          })}
        </div>
      </div>

      {isLoading ? (
        <div className="mt-6 rounded-2xl bg-mist/70 p-6 text-sm text-ink/45">
          Loading feature flow...
        </div>
      ) : !data || data.status !== "ready" ? (
        <div className="mt-6 rounded-2xl bg-mist/70 p-6 text-sm text-ink/45">
          Feature flow data is not available yet.
        </div>
      ) : (
        <div className="mt-6 space-y-4">
          {data.steps.map((step) => (
            <article
              key={`${data.feature}-${step.step}`}
              className="grid gap-4 rounded-[1.5rem] border border-black/10 bg-sand/60 p-5 lg:grid-cols-[84px_1fr]"
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-ink text-lg font-semibold text-white">
                {step.step}
              </div>
              <div>
                <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                  <h3 className="font-display text-2xl text-ink">{step.title}</h3>
                  <span className="rounded-full bg-white/90 px-3 py-1 text-xs uppercase tracking-[0.16em] text-ink/55">
                    {step.file_path}
                  </span>
                </div>
                <p className="mt-3 text-sm leading-7 text-ink/75">
                  {step.description}
                </p>
                {step.file_summary ? (
                  <p className="mt-3 rounded-2xl bg-white/80 px-4 py-3 text-sm text-ink/60">
                    {step.file_summary}
                  </p>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
