"use client";

/* FloorplanImportDialog — Layer 5B, upload → geometry.
 *
 * Upload a floor-plan image → a vision LLM reads its room program (rooms +
 * areas + adjacencies) → the multi-room layout solver + kernel produce a
 * modelled, furnished, dimensioned design + a GA plan sheet. The image analog
 * of the "prompt" front door, wired to POST /imports/floorplan/render.
 */

import { useCallback, useRef, useState } from "react";
import {
  ApiError,
  imports as importsApi,
  type FloorplanRenderResponse,
} from "@/lib/api-client";

const ACCEPT = ".png,.jpg,.jpeg,.webp";

type State = "idle" | "working" | "done" | "error";

export function FloorplanImportDialog({
  open,
  onClose,
  token,
}: {
  open: boolean;
  onClose: () => void;
  token: string | null | undefined;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [style, setStyle] = useState("");
  const [state, setState] = useState<State>("idle");
  const [result, setResult] = useState<FloorplanRenderResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"render" | "plan">("render");
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const reset = useCallback(() => {
    setFile(null);
    setPreview(null);
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
    setPreview(URL.createObjectURL(f));
    setResult(null);
    setState("idle");
    setError(null);
  };

  const run = async () => {
    if (!file) return;
    setState("working");
    setError(null);
    try {
      const res = await importsApi.renderFloorplan(token ?? undefined, file, style);
      setResult(res);
      setView("render");
      setState("done");
    } catch (e) {
      setState("error");
      if (e instanceof ApiError) {
        const detail = (e.body as { detail?: { message?: string } | string } | null)?.detail;
        const msg = typeof detail === "string" ? detail : detail?.message;
        setError(msg || `Reconstruction failed (${e.status}).`);
      } else {
        setError("Couldn't reach the backend. Is uvicorn running on :8000?");
      }
    }
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) pick(e.dataTransfer.files[0]);
  };

  if (!open) return null;

  const shown = view === "plan" && result?.plan_sheet ? result.plan_sheet : result?.render?.image;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Import floor plan"
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
              Upload · Floor plan
            </span>
            <h2 className="mt-1 text-[16px] text-ink-deep font-semibold tracking-[-0.01em]">
              Reconstruct from a plan
            </h2>
          </div>
          <button
            type="button"
            onClick={close}
            aria-label="Close floor-plan dialog"
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
            {preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview} alt="Floor plan" className="mx-auto max-h-40 w-auto object-contain mb-2" />
            ) : (
              <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-mute mb-1">
                ⤓ Drop a floor-plan image or click to choose
              </div>
            )}
            <div className="text-[11px] font-mono text-ink-soft">PNG · JPG · WEBP</div>
            {file ? (
              <div className="mt-1 font-mono text-[12px] text-ink-deep truncate">{file.name}</div>
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
              Style / theme (optional)
            </span>
            <input
              type="text"
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              placeholder="e.g. modern, scandinavian, minimalist"
              className="mt-1 w-full bg-paper border border-hairline rounded-sm px-3 py-2 text-[13px] text-ink-deep placeholder:text-ink-mute focus:border-graphite outline-none"
            />
          </label>

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
                  onClick={() => setView("plan")}
                  disabled={!result.plan_sheet}
                  className={`font-mono text-[10px] uppercase tracking-[0.12em] px-2 py-1 rounded-sm transition-colors disabled:opacity-30 ${
                    view === "plan" ? "bg-ink-deep text-paper" : "text-ink-soft hover:text-ink"
                  }`}
                >
                  Plan sheet
                </button>
                <span className="ml-auto font-mono text-[10px] text-ink-mute">
                  {result.room_count} rooms · {result.total_area_sqm} m²
                </span>
              </div>
              {shown ? (
                <div className="bg-paper-soft flex items-center justify-center p-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={shown} alt={view === "plan" ? "Plan sheet" : "Render"} className="max-h-[38vh] w-auto object-contain" />
                </div>
              ) : null}
              <div className="px-3 py-2 border-t border-hairline max-h-32 overflow-y-auto">
                <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute mb-1">
                  Rooms read from the plan
                </div>
                <ul className="grid grid-cols-2 gap-x-6 gap-y-0.5 text-[11px] font-mono">
                  {result.program.rooms.map((r) => (
                    <li key={r.id} className="flex items-baseline justify-between">
                      <span className="text-ink-deep">{r.type.replace(/_/g, " ")}</span>
                      <span className="text-ink-mute">{r.area_sqm} m²</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}

          {error ? <p className="text-[12px] font-mono text-brick">{error}</p> : null}
        </div>

        <div className="px-5 py-3 border-t border-hairline flex items-center justify-between shrink-0">
          <span className="text-[11px] font-mono uppercase tracking-[0.1em] text-ink-mute">
            {state === "working"
              ? "Reading plan → solving → rendering (~30–60s)"
              : state === "done"
              ? "Done"
              : file
              ? "Ready to reconstruct"
              : "Pick a floor-plan image"}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={close}
              className="text-[12px] font-medium px-3 py-1.5 text-ink-soft hover:text-ink rounded-sm transition-colors"
            >
              Close
            </button>
            <button
              type="button"
              onClick={run}
              disabled={!file || state === "working"}
              className="text-[12px] font-medium px-3 py-1.5 bg-ink-deep text-paper hover:bg-ink rounded-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {state === "working" ? "Working…" : state === "done" ? "Reconstruct again" : "Reconstruct"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
