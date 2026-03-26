"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import api from "../../../lib/api-client";
import {
  useAuthStore,
  useDesignGraphStore,
  useEstimateStore,
  useUIStore,
} from "../../../lib/store";
import EstimatePanel from "../../../components/estimate-panel";
import ObjectInspector from "../../../components/object-inspector";
import ThemeSwitcher from "../../../components/theme-switcher";
import VersionTimeline from "../../../components/version-timeline";

// Lazy-load the 3D viewer (heavy Three.js bundle)
const SceneViewer3D = dynamic(
  () => import("../../../components/scene-viewer-3d"),
  { ssr: false, loading: () => <div className="flex h-[500px] items-center justify-center text-ink/40">Loading 3D engine...</div> },
);

interface VersionSummary {
  id: string;
  version: number;
  change_type: string;
  change_summary: string;
  created_at: string;
}

export default function ProjectViewerPage() {
  const params = useParams();
  const projectId = params.id as string;
  const token = useAuthStore((s) => s.token);

  const { graphData, version, setGraphData, setGenerating, isGenerating } =
    useDesignGraphStore();
  const setEstimate = useEstimateStore((s) => s.setEstimate);
  const { sidePanel, setSidePanel } = useUIStore();

  const [projectName, setProjectName] = useState("");
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [editLoading, setEditLoading] = useState(false);

  // ── Load project data ──────────────────────────────────────────────────
  useEffect(() => {
    if (!token || !projectId) return;

    // Load project metadata
    api.projects.get(token, projectId).then((p) => setProjectName(p.name));

    // Load latest design version
    api.generation
      .getLatest(token, projectId)
      .then((res) => {
        const data = res as { graph_data: Record<string, unknown>; version: number };
        setGraphData(data.graph_data, data.version);
      })
      .catch(() => {
        /* no versions yet */
      });

    // Load version list
    api.generation
      .listVersions(token, projectId)
      .then((res) => {
        const data = res as { versions: VersionSummary[] };
        setVersions(data.versions ?? []);
      })
      .catch(() => {});

    // Load estimate
    api.estimates
      .getLatest(token, projectId)
      .then((est) => setEstimate(est as Record<string, unknown>))
      .catch(() => {});
  }, [token, projectId, setGraphData, setEstimate]);

  // ── Local edit handler ─────────────────────────────────────────────────
  const handleEditObject = useCallback(
    async (objectId: string, prompt: string) => {
      if (!token) return;
      setEditLoading(true);
      try {
        const result = await api.generation.edit(token, projectId, {
          object_id: objectId,
          prompt,
        });
        setGraphData(
          result.graph_data as Record<string, unknown>,
          result.version,
        );
        setEstimate(result.estimate as Record<string, unknown>);
      } catch {
        /* handle error */
      } finally {
        setEditLoading(false);
      }
    },
    [token, projectId, setGraphData, setEstimate],
  );

  // ── Theme switch handler ───────────────────────────────────────────────
  const handleThemeSwitch = useCallback(
    async (newStyle: string) => {
      if (!token) return;
      setGenerating(true);
      try {
        const result = await api.generation.switchTheme(token, projectId, {
          new_style: newStyle,
        });
        setGraphData(
          result.graph_data as Record<string, unknown>,
          result.version,
        );
        setEstimate(result.estimate as Record<string, unknown>);
      } catch {
        /* handle error */
      }
    },
    [token, projectId, setGraphData, setEstimate, setGenerating],
  );

  // ── Load specific version ──────────────────────────────────────────────
  const handleVersionSelect = useCallback(
    async (ver: number) => {
      if (!token) return;
      try {
        const res = await api.generation.getVersion(token, projectId, ver);
        const data = res as { graph_data: Record<string, unknown>; version: number };
        setGraphData(data.graph_data, data.version);

        const est = await api.estimates.getForVersion(token, projectId, ver);
        setEstimate(est as Record<string, unknown>);
      } catch {
        /* handle error */
      }
    },
    [token, projectId, setGraphData, setEstimate],
  );

  // ── Side panel tabs ────────────────────────────────────────────────────
  const panels = [
    { key: "3d" as const, label: "3D View" },
    { key: "estimate" as const, label: "Estimate" },
    { key: "versions" as const, label: "Versions" },
    { key: "materials" as const, label: "Materials" },
  ];

  return (
    <main className="mx-auto max-w-7xl px-6 py-6">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl text-ink">
            {projectName || "Project"}
          </h1>
          <p className="text-sm text-ink/50">
            Version {version} {isGenerating && "— Generating..."}
          </p>
        </div>
        <ThemeSwitcher onSwitch={handleThemeSwitch} isLoading={isGenerating} />
      </div>

      {/* Main layout: 2D/3D viewer + side panel */}
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        {/* Left: 3D scene */}
        <div className="space-y-4">
          <Suspense
            fallback={
              <div className="flex h-[500px] items-center justify-center rounded-2xl border border-black/10 bg-mist/50 text-ink/40">
                Loading...
              </div>
            }
          >
            <SceneViewer3D className="h-[500px]" />
          </Suspense>

          {/* Object inspector (below 3D) */}
          <ObjectInspector
            onEditSubmit={handleEditObject}
            isLoading={editLoading}
          />
        </div>

        {/* Right: side panel */}
        <div className="space-y-4">
          {/* Panel tabs */}
          <div className="flex gap-1 rounded-xl bg-mist/60 p-1">
            {panels.map((p) => (
              <button
                key={p.key}
                onClick={() => setSidePanel(p.key)}
                className={`flex-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-colors ${
                  sidePanel === p.key
                    ? "bg-white text-ink shadow-sm"
                    : "text-ink/50 hover:text-ink/70"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Panel content */}
          {sidePanel === "estimate" && <EstimatePanel />}
          {sidePanel === "versions" && (
            <VersionTimeline
              versions={versions}
              currentVersion={version}
              onSelect={handleVersionSelect}
            />
          )}
          {sidePanel === "materials" && (
            <MaterialsPanel graphData={graphData} />
          )}
          {sidePanel === "3d" && (
            <div className="rounded-2xl border border-black/10 bg-white/60 p-4 text-sm text-ink/60">
              <p>The 3D scene is shown in the main panel above.</p>
              <p className="mt-2">Click objects to select and edit them.</p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

// ── Materials sub-panel ──────────────────────────────────────────────────────

function MaterialsPanel({
  graphData,
}: {
  graphData: Record<string, unknown> | null;
}) {
  const materials =
    (graphData?.materials as Array<{
      id: string;
      name: string;
      category: string;
      color: string;
    }>) ?? [];

  if (!materials.length) {
    return (
      <div className="rounded-2xl border border-black/10 bg-white/60 p-4 text-sm text-ink/40">
        No materials defined yet.
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded-2xl border border-black/10 bg-white/60 p-4">
      <h4 className="text-sm font-medium text-ink/70">Materials</h4>
      {materials.map((mat) => (
        <div
          key={mat.id}
          className="flex items-center gap-3 rounded-lg bg-sand/50 px-3 py-2"
        >
          <div
            className="h-6 w-6 rounded-full border border-black/10"
            style={{ backgroundColor: mat.color || "#ccc" }}
          />
          <div>
            <p className="text-sm font-medium text-ink">{mat.name}</p>
            <p className="text-xs text-ink/50">{mat.category}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
