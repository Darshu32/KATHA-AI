"use client";

/* ModelImportDialog — Layer 5B, Tier 1 upload surface.
 *
 * The "upload" front door (vs the "prompt" front door): an architect drops an
 * existing 3D model (OBJ/GLB/glTF/STL/PLY/OFF) and the backend renders it
 * photoreal via the kernel camera + Nano Banana finish, returning a spec sheet
 * (front/side/top silhouettes) and overall dimensions. Wired to
 * POST /imports/3d/render.
 */

import { useCallback, useRef, useState } from "react";
import {
  ApiError,
  imports as importsApi,
  projects as projectsApi,
  type Model3DRenderResponse,
  type Reconstruct3DResponse,
} from "@/lib/api-client";

const ACCEPT = ".obj,.glb,.gltf,.stl,.ply,.off";

type State = "idle" | "rendering" | "done" | "error";

export function ModelImportDialog({
  open,
  onClose,
  token,
  onOpened,
}: {
  open: boolean;
  onClose: () => void;
  token: string | null | undefined;
  onOpened?: (projectId: string, version: number, name: string) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [style, setStyle] = useState("");
  const [state, setState] = useState<State>("idle");
  const [mode, setMode] = useState<"whole" | "parts">("whole");
  const [result, setResult] = useState<Model3DRenderResponse | Reconstruct3DResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"render" | "sheet">("render");
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const reset = useCallback(() => {
    setFile(null);
    setStyle("");
    setState("idle");
    setResult(null);
    setError(null);
    setView("render");
  }, []);

  const close = () => {
    reset();
    onClose();
  };

  const pick = (f: File | null) => {
    if (!f) return;
    setFile(f);
    setResult(null);
    setState("idle");
    setError(null);
  };

  const render = async () => {
    if (!file) return;
    setState("rendering");
    setError(null);
    try {
      const res =
        mode === "parts"
          ? await importsApi.reconstruct3d(token ?? undefined, file, style)
          : await importsApi.render3d(token ?? undefined, file, style);
      setResult(res);
      setView("render");
      setState("done");
    } catch (e) {
      setState("error");
      if (e instanceof ApiError) {
        const detail = (e.body as { detail?: { message?: string } | string } | null)?.detail;
        const msg = typeof detail === "string" ? detail : detail?.message;
        setError(msg || `Render failed (${e.status}). Check the model file.`);
      } else {
        setError("Couldn't reach the backend. Is uvicorn running on :8000?");
      }
    }
  };

  const openAsProject = async () => {
    if (!result || !("part_count" in result)) return;
    setSaving(true);
    setError(null);
    try {
      const res = await projectsApi.importProject(token ?? undefined, {
        name: (file?.name || "Reconstructed model").replace(/\.[^.]+$/, ""),
        graph: result.graph,
        render_image: result.render?.image ?? null,
        hotspots: result.hotspots,
        project_type: "furniture",
      });
      onOpened?.(res.project_id, res.version, res.name);
      close();
    } catch {
      setError("Couldn't save as a project.");
    } finally {
      setSaving(false);
    }
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) pick(e.dataTransfer.files[0]);
  };

  if (!open) return null;

  const whole = result && "dimensions_m" in result ? result : null;
  const parts = result && "part_count" in result ? result : null;
  const dims = whole?.dimensions_m;
  const uk = whole?.units_known;
  const fmt = (m: number) => (uk ? `${Math.round(m * 1000)} mm` : m.toFixed(3));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Import 3D model"
      className="fixed inset-0 z-40 flex items-start justify-center pt-16 px-4"
      onKeyDown={(e) => {
        if (e.key === "Escape") close();
      }}
    >
      <div className="absolute inset-0 bg-ink-deep/30" onClick={close} aria-hidden="true" />
      <div className="relative w-full max-w-2xl bg-paper border border-graphite rounded-md shadow-card overflow-hidden max-h-[86vh] flex flex-col">
        <div className="px-5 py-3 border-b border-hairline flex items-baseline justify-between shrink-0">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-mute">
              Upload · 3D model
            </span>
            <h2 className="mt-1 text-[16px] text-ink-deep font-semibold tracking-[-0.01em]">
              Render an existing model
            </h2>
          </div>
          <button
            type="button"
            onClick={close}
            aria-label="Close 3D import dialog"
            className="text-ink-mute hover:text-ink text-[14px] font-mono p-1"
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 overflow-y-auto">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            className={`border border-dashed rounded-md px-4 py-6 text-center cursor-pointer transition-colors ${
              isDragging
                ? "border-pencil bg-pencil-bg/40"
                : "border-graphite hover:border-ink-soft hover:bg-paper-soft"
            }`}
          >
            <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-mute mb-1">
              {file ? "⤓ Replace model" : "⤓ Drop a 3D model or click to choose"}
            </div>
            <div className="text-[11px] font-mono text-ink-soft">
              OBJ · GLB · glTF · STL · PLY · OFF
            </div>
            {file ? (
              <div className="mt-2 font-mono text-[12px] text-ink-deep truncate">
                {file.name} · {fmtSize(file.size)}
              </div>
            ) : null}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              onChange={(e) => {
                pick(e.target.files?.[0] ?? null);
                e.target.value = "";
              }}
              className="hidden"
            />
          </div>

          <label className="block">
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-mute">
              Material / finish (optional)
            </span>
            <input
              type="text"
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              placeholder="e.g. walnut and tan leather"
              className="mt-1 w-full bg-paper border border-hairline rounded-sm px-3 py-2 text-[13px] text-ink-deep placeholder:text-ink-mute focus:border-graphite outline-none"
            />
            <span className="mt-1 block text-[11px] text-ink-soft">
              An uploaded mesh carries no materials — this guides the photoreal finish.
            </span>
          </label>

          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-mute">
              Mode
            </span>
            {(["whole", "parts"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  setMode(m);
                  setResult(null);
                  setState("idle");
                }}
                className={`font-mono text-[10px] uppercase tracking-[0.12em] px-2 py-1 rounded-sm transition-colors ${
                  mode === m
                    ? "bg-ink-deep text-paper"
                    : "text-ink-soft hover:text-ink border border-hairline"
                }`}
              >
                {m === "whole" ? "Render whole" : "Editable parts"}
              </button>
            ))}
          </div>

          {state === "done" && result ? (
            <div className="border border-hairline rounded-md overflow-hidden">
              <div className="px-3 py-2 border-b border-hairline flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setView("render")}
                  className={`font-mono text-[10px] uppercase tracking-[0.12em] px-2 py-1 rounded-sm transition-colors ${
                    view === "render" ? "bg-ink-deep text-paper" : "text-ink-soft hover:text-ink"
                  }`}
                >
                  Render
                </button>
                <button
                  type="button"
                  onClick={() => setView("sheet")}
                  disabled={!result.spec_sheet}
                  className={`font-mono text-[10px] uppercase tracking-[0.12em] px-2 py-1 rounded-sm transition-colors disabled:opacity-30 ${
                    view === "sheet" ? "bg-ink-deep text-paper" : "text-ink-soft hover:text-ink"
                  }`}
                >
                  Spec sheet
                </button>
                <span className="ml-auto font-mono text-[10px] text-ink-mute">
                  {parts ? `${parts.part_count} parts` : result.render?.kind}
                  {result.render && !result.render.finished ? " · clay" : ""}
                </span>
              </div>
              <div className="bg-paper-soft flex items-center justify-center p-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={view === "sheet" && result.spec_sheet ? result.spec_sheet : (result.render?.image ?? "")}
                  alt={view === "sheet" ? "Model spec sheet" : "Model render"}
                  className="max-h-[42vh] w-auto object-contain"
                />
              </div>
              {parts ? (
                <div className="px-3 py-2 border-t border-hairline max-h-32 overflow-y-auto">
                  <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute mb-1">
                    {parts.part_count} editable part{parts.part_count === 1 ? "" : "s"} · each selectable
                  </div>
                  <ul className="grid grid-cols-2 gap-x-6 gap-y-0.5 text-[11px] font-mono">
                    {parts.parts.map((p) => (
                      <li key={p.id} className="flex items-baseline justify-between">
                        <span className="text-ink-deep">{p.type}</span>
                        <span className="text-ink-mute">
                          {p.dimensions_mm.length}×{p.dimensions_mm.width}×{p.dimensions_mm.height}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : whole ? (
                <div className="px-3 py-2 border-t border-hairline grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] font-mono">
                  <Row k="Length" v={dims ? fmt(dims.length) : "—"} />
                  <Row k="Triangles" v={whole.mesh.triangles.toLocaleString()} />
                  <Row k="Depth" v={dims ? fmt(dims.depth) : "—"} />
                  <Row k="Watertight" v={whole.mesh.watertight ? "yes" : "no"} />
                  <Row k="Height" v={dims ? fmt(dims.height) : "—"} />
                  <Row k="Scale" v={uk ? "metres (glTF)" : "unitless (OBJ)"} />
                </div>
              ) : null}
            </div>
          ) : null}

          {error ? <p className="text-[12px] font-mono text-brick">{error}</p> : null}
        </div>

        <div className="px-5 py-3 border-t border-hairline flex items-center justify-between shrink-0">
          <span className="text-[11px] font-mono uppercase tracking-[0.1em] text-ink-mute">
            {state === "rendering"
              ? "Rendering… kernel + finish (~10–30s)"
              : state === "done"
              ? "Done"
              : file
              ? "Ready to render"
              : "Pick a model to begin"}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={close}
              className="text-[12px] font-medium px-3 py-1.5 text-ink-soft hover:text-ink rounded-sm transition-colors"
            >
              Close
            </button>
            {parts ? (
              <button
                type="button"
                onClick={openAsProject}
                disabled={saving}
                className="text-[12px] font-medium px-3 py-1.5 border border-graphite text-ink-deep hover:bg-paper-soft rounded-sm transition-colors disabled:opacity-40"
              >
                {saving ? "Opening…" : "Open as project"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={render}
              disabled={!file || state === "rendering"}
              className="text-[12px] font-medium px-3 py-1.5 bg-ink-deep text-paper hover:bg-ink rounded-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {state === "rendering" ? "Rendering…" : state === "done" ? "Render again" : "Render"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-ink-mute">{k}</span>
      <span className="text-ink-deep">{v}</span>
    </div>
  );
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
