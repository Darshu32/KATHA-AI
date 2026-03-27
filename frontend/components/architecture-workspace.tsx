"use client";

import { startTransition, useEffect, useMemo, useState } from "react";
import api, {
  type ArchitectureAskResponse,
  type ArchitectureDependencyResponse,
  type ArchitectureFeatureFlowResponse,
  type ArchitectureQualityResponse,
  type ArchitectureSummaryResponse,
  type ArchitectureStatusResponse,
} from "../lib/api-client";
import { useAuthStore } from "../lib/store";
import FeatureFlowPanel from "./feature-flow-panel";

type LoadingState = "idle" | "loading" | "error";

const FEATURE_OPTIONS = [
  "initial_generation",
  "local_edit",
  "theme_switch",
  "estimation",
] as const;

const DEPENDENCY_EXAMPLES = [
  "generation_pipeline",
  "frontend/app/project/[id]/page.tsx",
  "design_graph_service",
];

const QUESTION_SUGGESTIONS = [
  "How does initial generation work?",
  "What depends on generation_pipeline?",
  "How does estimation flow through the system?",
];

function labelize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatCommit(hash: string): string {
  return hash ? hash.slice(0, 7) : "local";
}

export default function ArchitectureWorkspace() {
  const token = useAuthStore((state) => state.token) ?? undefined;
  const [summary, setSummary] = useState<ArchitectureSummaryResponse | null>(null);
  const [status, setStatus] = useState<ArchitectureStatusResponse | null>(null);
  const [quality, setQuality] = useState<ArchitectureQualityResponse | null>(null);
  const [activeFeature, setActiveFeature] = useState<string>("initial_generation");
  const [featureFlow, setFeatureFlow] = useState<ArchitectureFeatureFlowResponse | null>(null);
  const [dependencyQuery, setDependencyQuery] = useState("generation_pipeline");
  const [dependencyData, setDependencyData] = useState<ArchitectureDependencyResponse | null>(null);
  const [question, setQuestion] = useState("How does initial generation work?");
  const [answer, setAnswer] = useState<ArchitectureAskResponse | null>(null);
  const [summaryState, setSummaryState] = useState<LoadingState>("loading");
  const [featureState, setFeatureState] = useState<LoadingState>("loading");
  const [dependencyState, setDependencyState] = useState<LoadingState>("idle");
  const [askState, setAskState] = useState<LoadingState>("idle");
  const [refreshState, setRefreshState] = useState<LoadingState>("idle");

  const loadFreshness = async () => {
    const [nextStatus, nextQuality] = await Promise.all([
      api.architecture.status(token),
      api.architecture.quality(token),
    ]);
    setStatus(nextStatus);
    setQuality(nextQuality);
    return nextStatus;
  };

  const loadSummary = async () => {
    const data = await api.architecture.summary(token);
    setSummary(data);
    return data;
  };

  useEffect(() => {
    setSummaryState("loading");
    Promise.all([loadSummary(), loadFreshness()])
      .catch(() => {
        setSummary(null);
        setStatus(null);
        setQuality(null);
      })
      .finally(() => setSummaryState("idle"));
  }, [token]);

  useEffect(() => {
    if (!status || status.freshness !== "stale" || refreshState === "loading") {
      return;
    }

    void handleRefresh(false);
  }, [status, refreshState]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadFreshness().catch(() => undefined);
    }, 30000);

    return () => window.clearInterval(timer);
  }, [token]);

  useEffect(() => {
    setFeatureState("loading");
    api.architecture
      .featureFlow(token, activeFeature)
      .then((data) => setFeatureFlow(data))
      .catch(() => setFeatureFlow(null))
      .finally(() => setFeatureState("idle"));
  }, [activeFeature, token]);

  const topNodeTypes = useMemo(() => {
    if (!summary) return [];
    return Object.entries(summary.overview.top_node_types)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);
  }, [summary]);

  const handleFeatureChange = (feature: string) => {
    startTransition(() => {
      setActiveFeature(feature);
    });
  };

  const handleDependencyLookup = async (nextQuery?: string) => {
    const resolvedQuery = (nextQuery ?? dependencyQuery).trim();
    if (!resolvedQuery) return;

    setDependencyState("loading");
    setDependencyQuery(resolvedQuery);
    try {
      const data = await api.architecture.dependencies(token, resolvedQuery);
      setDependencyData(data);
      setDependencyState("idle");
    } catch {
      setDependencyData(null);
      setDependencyState("error");
    }
  };

  const handleAsk = async (nextQuestion?: string) => {
    const resolvedQuestion = (nextQuestion ?? question).trim();
    if (!resolvedQuestion) return;

    setAskState("loading");
    setQuestion(resolvedQuestion);
    try {
      const data = await api.architecture.ask(token, resolvedQuestion);
      setAnswer(data);
      setAskState("idle");
    } catch {
      setAnswer(null);
      setAskState("error");
    }
  };

  const handleRefresh = async (force: boolean) => {
    setRefreshState("loading");
    try {
      await api.architecture.refresh(token, force);
      await Promise.all([loadFreshness(), loadSummary()]);
      setRefreshState("idle");
    } catch {
      setRefreshState("error");
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-8 px-6 py-10">
      <section className="grid gap-6 rounded-[2rem] border border-black/10 bg-white/65 p-8 shadow-panel lg:grid-cols-[1.3fr_0.7fr]">
        <div className="space-y-5">
          <span className="inline-flex rounded-full border border-sage/30 bg-sage/10 px-4 py-2 text-sm font-semibold uppercase tracking-[0.18em] text-sage">
            Architecture Workbench
          </span>
          <div className="space-y-3">
            <h1 className="max-w-3xl font-display text-5xl leading-tight text-ink">
              Make the system explain itself with evidence.
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-ink/75">
              This workspace turns the backend architecture graph into something
              a builder can explore: overview, feature flows, dependency impact,
              and grounded answers with file citations.
            </p>
          </div>
        </div>

        <div className="rounded-[1.75rem] bg-ink p-6 text-white">
          <p className="text-sm uppercase tracking-[0.18em] text-white/55">
            Snapshot
          </p>
          {summaryState === "loading" ? (
            <div className="mt-6 text-sm text-white/60">Loading architecture summary...</div>
          ) : summary ? (
            <div className="mt-6 space-y-4">
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.16em] text-white/50">
                  Repository
                </p>
                <p className="mt-2 text-xl font-semibold">{summary.snapshot.repo_name}</p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <MetricCard label="Files" value={String(summary.overview.file_count)} />
                <MetricCard label="Nodes" value={String(summary.overview.node_count)} />
                <MetricCard label="Modules" value={String(summary.overview.modules.length)} />
                <MetricCard label="Commit" value={formatCommit(summary.snapshot.commit_hash)} />
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <div className="flex items-center justify-between">
                  <p className="text-xs uppercase tracking-[0.16em] text-white/50">
                    Freshness
                  </p>
                  <span
                    className={`rounded-full px-3 py-1 text-xs uppercase tracking-[0.16em] ${
                      summary.freshness.status === "synced"
                        ? "bg-emerald-500/20 text-emerald-200"
                        : "bg-amber-500/20 text-amber-200"
                    }`}
                  >
                    {summary.freshness.status}
                  </span>
                </div>
                <p className="mt-3 text-sm text-white/70">
                  {summary.drift.changed_file_count} changed, {summary.drift.new_file_count} new,{" "}
                  {summary.drift.deleted_file_count} deleted file(s).
                </p>
              </div>
            </div>
          ) : (
            <div className="mt-6 text-sm text-rose-200">
              Architecture summary is unavailable right now.
            </div>
          )}
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-[1.75rem] border border-black/10 bg-white/70 p-6 shadow-panel">
          <p className="text-sm uppercase tracking-[0.18em] text-clay">
            System Overview
          </p>
          <h2 className="mt-2 font-display text-3xl text-ink">
            Indexed modules and dominant node types
          </h2>

          {summaryState === "loading" ? (
            <div className="mt-6 rounded-2xl bg-mist/70 p-5 text-sm text-ink/45">
              Gathering architecture overview...
            </div>
          ) : summary ? (
            <div className="mt-6 grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
              <div>
                <p className="text-xs uppercase tracking-[0.16em] text-ink/45">
                  Modules
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {summary.overview.modules.map((moduleName) => (
                    <span
                      key={moduleName}
                      className="rounded-full bg-sand px-3 py-1 text-sm text-ink/70"
                    >
                      {moduleName}
                    </span>
                  ))}
                </div>
                <p className="mt-6 text-xs uppercase tracking-[0.16em] text-ink/45">
                  Indexed files
                </p>
                <div className="mt-3 space-y-2">
                  {summary.files.slice(0, 5).map((file) => (
                    <div key={file.file_path} className="rounded-2xl bg-sand/65 px-4 py-3">
                      <p className="text-sm font-medium text-ink">{file.file_path}</p>
                      <p className="mt-1 text-sm text-ink/60">{file.summary}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-[1.5rem] bg-ink p-5 text-white">
                <p className="text-xs uppercase tracking-[0.16em] text-white/55">
                  Node type distribution
                </p>
                <div className="mt-4 space-y-3">
                  {topNodeTypes.map(([type, count]) => (
                    <div key={type}>
                      <div className="mb-1 flex items-center justify-between text-sm">
                        <span>{labelize(type)}</span>
                        <span className="text-white/65">{count}</span>
                      </div>
                      <div className="h-2 rounded-full bg-white/10">
                        <div
                          className="h-2 rounded-full bg-clay"
                          style={{
                            width: `${Math.max(
                              12,
                              (count / Math.max(topNodeTypes[0]?.[1] ?? 1, 1)) * 100,
                            )}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="mt-6 rounded-2xl bg-rose-50 p-5 text-sm text-rose-700">
              The backend summary could not be loaded.
            </div>
          )}
        </div>

        <section className="rounded-[1.75rem] border border-black/10 bg-white/70 p-6 shadow-panel">
          <p className="text-sm uppercase tracking-[0.18em] text-clay">
            Freshness And Quality
          </p>
          <h2 className="mt-2 font-display text-3xl text-ink">
            Keep the architecture graph current
          </h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <StatusCard
              label="Freshness"
              value={status?.freshness ?? "unknown"}
              tone={status?.freshness === "synced" ? "good" : "warn"}
              detail={`${status?.drift.changed_file_count ?? 0} changed · ${status?.drift.new_file_count ?? 0} new`}
            />
            <StatusCard
              label="Quality Score"
              value={quality ? `${quality.score}/100` : "--"}
              tone={(quality?.score ?? 0) >= 80 ? "good" : "warn"}
              detail={`${quality?.issue_count ?? 0} issue(s)`}
            />
          </div>
          <div className="mt-4 rounded-[1.5rem] bg-sand/65 p-4">
            <p className="text-sm font-medium text-ink">Recommendations</p>
            <div className="mt-3 space-y-2 text-sm text-ink/65">
              {(quality?.recommendations ?? ["No recommendations available yet."]).map((item) => (
                <p key={item}>{item}</p>
              ))}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void handleRefresh(false)}
              className="rounded-xl bg-ink px-5 py-3 font-medium text-white transition-colors hover:bg-ink/90"
            >
              {refreshState === "loading" ? "Refreshing..." : "Refresh if stale"}
            </button>
            <button
              type="button"
              onClick={() => void handleRefresh(true)}
              className="rounded-xl border border-black/10 bg-white px-5 py-3 font-medium text-ink transition-colors hover:bg-sand"
            >
              Force full refresh
            </button>
          </div>
          {refreshState === "error" ? (
            <div className="mt-4 rounded-2xl bg-rose-50 p-4 text-sm text-rose-700">
              Architecture refresh failed.
            </div>
          ) : null}
        </section>

        <section className="rounded-[1.75rem] border border-black/10 bg-white/70 p-6 shadow-panel">
          <p className="text-sm uppercase tracking-[0.18em] text-sage">
            Ask Architecture
          </p>
          <h2 className="mt-2 font-display text-3xl text-ink">
            Grounded system answers
          </h2>

          <div className="mt-6 space-y-4">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={4}
              className="w-full resize-none rounded-2xl border border-black/10 bg-sand/55 px-4 py-3 text-ink focus:border-clay/40 focus:outline-none focus:ring-2 focus:ring-clay/20"
              placeholder="How does initial generation work?"
            />
            <div className="flex flex-wrap gap-2">
              {QUESTION_SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => void handleAsk(suggestion)}
                  className="rounded-full bg-mist px-3 py-1.5 text-sm text-ink/70 transition-colors hover:bg-sand"
                >
                  {suggestion}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => void handleAsk()}
              className="rounded-xl bg-ink px-5 py-3 font-medium text-white transition-colors hover:bg-ink/90"
            >
              {askState === "loading" ? "Thinking..." : "Ask the architecture graph"}
            </button>
          </div>

          {answer ? (
            <div className="mt-6 space-y-4 rounded-[1.5rem] bg-ink p-5 text-white">
              <div className="flex items-center justify-between">
                <span className="rounded-full bg-white/10 px-3 py-1 text-xs uppercase tracking-[0.16em] text-white/65">
                  {answer.mode}
                </span>
                <span className="text-xs text-white/55">
                  {answer.citations.length} citation(s)
                </span>
              </div>
              <p className="text-sm leading-7 text-white/85">{answer.answer}</p>
              <div className="flex flex-wrap gap-2">
                {answer.citations.map((citation) => (
                  <span
                    key={citation}
                    className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/75"
                  >
                    {citation}
                  </span>
                ))}
              </div>
            </div>
          ) : askState === "error" ? (
            <div className="mt-6 rounded-2xl bg-rose-50 p-4 text-sm text-rose-700">
              The architecture question could not be answered right now.
            </div>
          ) : null}
        </section>
      </section>

      <FeatureFlowPanel
        activeFeature={activeFeature}
        data={featureFlow}
        isLoading={featureState === "loading"}
        onSelectFeature={handleFeatureChange}
      />

      <section className="grid gap-6 lg:grid-cols-[0.82fr_1.18fr]">
        <section className="rounded-[1.75rem] border border-black/10 bg-white/70 p-6 shadow-panel">
          <p className="text-sm uppercase tracking-[0.18em] text-clay">
            Dependency Inspector
          </p>
          <h2 className="mt-2 font-display text-3xl text-ink">
            Impact analysis for files and symbols
          </h2>
          <p className="mt-3 text-sm leading-7 text-ink/65">
            Search a file path, function, or service name to see who points to
            it and what it points to.
          </p>

          <div className="mt-6 space-y-4">
            <input
              value={dependencyQuery}
              onChange={(event) => setDependencyQuery(event.target.value)}
              className="w-full rounded-2xl border border-black/10 bg-sand/55 px-4 py-3 text-ink focus:border-clay/40 focus:outline-none focus:ring-2 focus:ring-clay/20"
              placeholder="generation_pipeline"
            />
            <div className="flex flex-wrap gap-2">
              {DEPENDENCY_EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => void handleDependencyLookup(example)}
                  className="rounded-full bg-mist px-3 py-1.5 text-sm text-ink/70 transition-colors hover:bg-sand"
                >
                  {example}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => void handleDependencyLookup()}
              className="rounded-xl bg-ink px-5 py-3 font-medium text-white transition-colors hover:bg-ink/90"
            >
              {dependencyState === "loading" ? "Inspecting..." : "Inspect dependencies"}
            </button>
          </div>

          {dependencyData?.focus ? (
            <div className="mt-6 rounded-[1.5rem] bg-sand/75 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-ink/45">
                Focus node
              </p>
              <h3 className="mt-2 font-display text-2xl text-ink">
                {dependencyData.focus.name}
              </h3>
              <p className="mt-2 text-sm text-ink/65">
                {dependencyData.focus.node_type} · {dependencyData.focus.file_path || "generated reference"}
              </p>
            </div>
          ) : dependencyState === "error" ? (
            <div className="mt-6 rounded-2xl bg-rose-50 p-4 text-sm text-rose-700">
              Dependency analysis failed.
            </div>
          ) : dependencyData?.message ? (
            <div className="mt-6 rounded-2xl bg-mist/70 p-4 text-sm text-ink/55">
              {dependencyData.message}
            </div>
          ) : null}
        </section>

        <section className="grid gap-6 lg:grid-cols-2">
          <DependencyList
            title="Incoming"
            subtitle="Who depends on this node"
            items={dependencyData?.incoming ?? []}
          />
          <DependencyList
            title="Outgoing"
            subtitle="What this node depends on"
            items={dependencyData?.outgoing ?? []}
          />
        </section>
      </section>
    </main>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <p className="text-xs uppercase tracking-[0.16em] text-white/50">{label}</p>
      <p className="mt-2 text-xl font-semibold">{value}</p>
    </div>
  );
}

function DependencyList({
  title,
  subtitle,
  items,
}: {
  title: string;
  subtitle: string;
  items: Array<{
    edge_type: string;
    name: string;
    node_type: string;
    file_path: string;
    symbol_path: string;
  }>;
}) {
  return (
    <section className="rounded-[1.75rem] border border-black/10 bg-white/70 p-6 shadow-panel">
      <p className="text-sm uppercase tracking-[0.18em] text-sage">{title}</p>
      <h2 className="mt-2 font-display text-3xl text-ink">{subtitle}</h2>
      {items.length === 0 ? (
        <div className="mt-6 rounded-2xl bg-mist/70 p-5 text-sm text-ink/45">
          No tracked dependencies yet.
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          {items.map((item) => (
            <div
              key={`${title}-${item.symbol_path}`}
              className="rounded-[1.35rem] bg-sand/75 px-4 py-4"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-ink">{item.name}</p>
                  <p className="mt-1 text-sm text-ink/60">
                    {item.node_type} · {item.file_path || "generated reference"}
                  </p>
                </div>
                <span className="rounded-full bg-white/90 px-3 py-1 text-xs uppercase tracking-[0.16em] text-ink/55">
                  {item.edge_type}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function StatusCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "good" | "warn";
}) {
  return (
    <div className="rounded-[1.35rem] bg-mist/70 p-4">
      <p className="text-xs uppercase tracking-[0.16em] text-ink/45">{label}</p>
      <div className="mt-2 flex items-center gap-3">
        <span
          className={`h-3 w-3 rounded-full ${
            tone === "good" ? "bg-emerald-500" : "bg-amber-500"
          }`}
        />
        <p className="font-display text-2xl text-ink">{value}</p>
      </div>
      <p className="mt-2 text-sm text-ink/60">{detail}</p>
    </div>
  );
}
