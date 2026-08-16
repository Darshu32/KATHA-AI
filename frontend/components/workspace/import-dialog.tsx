"use client";

/* ImportDialog — BRD Layer 5B import surface (the file-upload UI).
 *
 * The backend has full deterministic importers for PDF, DOCX, DXF,
 * STEP, OBJ, CSV, XLSX, images, and plain text — but until now there
 * was no way for an architect to actually upload anything from the
 * web UI. This dialog closes that gap.
 *
 * Flow: pick or drop files → POST /imports/parse → render each file's
 * parsed summary + warnings → "Use as brief" joins extracted text into
 * the prompt textarea so the next Generate call carries the imported
 * context. The richer "merge into current project graph" path
 * (POST /imports/advisor) is wired in api-client but deliberately not
 * surfaced here; that's a v2 flow once the edit loop has been verified
 * end-to-end against a real backend.
 */

import { useCallback, useRef, useState } from "react";
import {
  ApiError,
  imports as importsApi,
  type ImportedFilePayload,
} from "@/lib/api-client";

const ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.psd,.psb,.dxf,.dwg,.ifc,.ifczip,.3dm,.skp,.cdr,.step,.stp,.iges,.obj,.fbx,.gltf,.csv,.xlsx,.xls,.docx,.txt,.md";

const FORMAT_HINTS: { label: string; exts: string }[] = [
  { label: "Briefs", exts: "pdf · docx · txt · md" },
  { label: "BIM", exts: "ifc (Revit · ArchiCAD · Vectorworks)" },
  { label: "Plans", exts: "dxf · dwg · cdr · step" },
  { label: "3D", exts: "obj · fbx · gltf · 3dm · skp" },
  { label: "Data", exts: "csv · xlsx" },
  { label: "Reference", exts: "png · jpg · psd" },
];

type DialogState = "idle" | "parsing" | "ready" | "error";

export function ImportDialog({
  open,
  onClose,
  onApply,
  token,
}: {
  open: boolean;
  onClose: () => void;
  /** Joined extracted content; the workspace appends this to the prompt
   *  textarea so the next Generate call carries the imported context. */
  onApply: (briefText: string, payloads: ImportedFilePayload[]) => void;
  token: string | undefined;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [state, setState] = useState<DialogState>("idle");
  const [results, setResults] = useState<ImportedFilePayload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const reset = useCallback(() => {
    setFiles([]);
    setResults([]);
    setState("idle");
    setError(null);
  }, []);

  const close = () => {
    reset();
    onClose();
  };

  const addFiles = (incoming: FileList | File[]) => {
    const arr = Array.from(incoming);
    setFiles((prev) => [...prev, ...arr]);
    setResults([]);
    setState("idle");
    setError(null);
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
    setResults([]);
    setState("idle");
  };

  const parseAll = async () => {
    if (files.length === 0) return;
    setState("parsing");
    setError(null);
    try {
      const res = await importsApi.parse(token, files);
      setResults(res.imports);
      setState("ready");
    } catch (e) {
      setState("error");
      if (e instanceof ApiError) {
        setError(`Parse failed (${e.status}). Check the file types.`);
      } else {
        setError("Couldn't reach the backend. Is uvicorn running on :8000?");
      }
    }
  };

  /* Build the brief text we paste into the prompt — the ACTUAL extracted
     content, not the meta-summary. Field names mirror what the importers
     return (text_excerpt / brief_signals / headers+sample_rows / bbox / spaces)
     so a real brief, schedule or model feeds the next Generate with substance. */
  const buildBriefText = (): string => {
    return results
      .map((r) => {
        const ex = (r.extracted ?? {}) as Record<string, unknown>;
        const lines: string[] = [`— from ${r.filename} —`];

        // Prose briefs (txt / md / pdf / docx / dxf notes)
        const text = (ex.text_excerpt ?? ex.text) as unknown;
        if (typeof text === "string" && text.trim()) lines.push(text.trim().slice(0, 1200));

        // Detected anchors (budget / dimensions / rooms / style / materials)
        const sig = ex.brief_signals as Record<string, unknown> | undefined;
        if (sig) {
          const asRaw = (v: unknown) =>
            Array.isArray(v) ? v.map((x) => (x as { raw?: string })?.raw ?? x).join(", ") : "";
          const asList = (v: unknown) => (Array.isArray(v) ? (v as string[]).join(", ") : "");
          const anchors = [
            ["Rooms", asList(sig.rooms_mentioned)],
            ["Style", asList(sig.styles_mentioned)],
            ["Materials", asList(sig.materials_mentioned)],
            ["Budget", asRaw(sig.budgets)],
            ["Dimensions", asRaw(sig.dimensions)],
            ["Timeline", asRaw(sig.timelines)],
          ].filter(([, v]) => v);
          if (anchors.length) lines.push(anchors.map(([k, v]) => `${k}: ${v}`).join(" · "));
        }

        // Tabular (csv / xlsx / step headers)
        const headers = ex.headers as unknown;
        if (Array.isArray(headers) && headers.length) {
          const rc = ex.row_count as number | undefined;
          lines.push(`Schedule [${headers.join(", ")}]${rc ? ` — ${rc} rows` : ""}`);
          const samples = ex.sample_rows as unknown;
          if (Array.isArray(samples) && samples.length)
            lines.push(samples.slice(0, 8).map((s) => JSON.stringify(s)).join("\n").slice(0, 600));
        }

        // Geometry (obj / ifc / step / dxf) — overall size + room count
        if (ex.bbox) lines.push(`Overall size: ${JSON.stringify(ex.bbox).slice(0, 220)}`);
        if (Array.isArray(ex.spaces) && ex.spaces.length) lines.push(`${ex.spaces.length} space(s) in the model`);

        // Nothing substantive extracted → at least carry the one-line summary.
        if (lines.length === 1) lines.push(r.summary);
        return lines.join("\n");
      })
      .join("\n\n");
  };

  const apply = () => {
    onApply(buildBriefText(), results);
    close();
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) addFiles(e.dataTransfer.files);
  };

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Import files"
      className="fixed inset-0 z-40 flex items-start justify-center pt-20 px-4"
      onKeyDown={(e) => {
        if (e.key === "Escape") close();
      }}
    >
      <div
        className="absolute inset-0 bg-ink-deep/30"
        onClick={close}
        aria-hidden="true"
      />
      <div className="relative w-full max-w-xl bg-paper border border-graphite rounded-md shadow-card overflow-hidden">
        <div className="px-5 py-3 border-b border-hairline flex items-baseline justify-between">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-mute">
              Import
            </span>
            <h2 className="mt-1 text-[16px] text-ink-deep font-semibold tracking-[-0.01em]">
              Add briefs, plans, references
            </h2>
          </div>
          <button
            type="button"
            onClick={close}
            aria-label="Close import dialog"
            className="text-ink-mute hover:text-ink text-[14px] font-mono p-1"
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            className={`border border-dashed rounded-md px-4 py-7 text-center cursor-pointer transition-colors ${
              isDragging
                ? "border-pencil bg-pencil-bg/40"
                : "border-graphite hover:border-ink-soft hover:bg-paper-soft"
            }`}
          >
            <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-mute mb-2">
              ⤓ Drop files or click to choose
            </div>
            <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-[11px] font-mono text-ink-soft">
              {FORMAT_HINTS.map((g) => (
                <span key={g.label}>
                  <span className="text-ink-mute">{g.label}</span>{" "}
                  <span>{g.exts}</span>
                </span>
              ))}
            </div>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPT}
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files);
                e.target.value = "";
              }}
              className="hidden"
            />
          </div>

          {files.length > 0 ? (
            <div className="border border-hairline rounded-md">
              <div className="px-3 py-2 border-b border-hairline flex items-baseline justify-between">
                <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-mute">
                  Queued · {String(files.length).padStart(2, "0")}
                </span>
                {state === "ready" ? (
                  <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-pencil">
                    parsed
                  </span>
                ) : null}
              </div>
              <ul className="divide-y divide-hairline">
                {files.map((f, i) => {
                  const r = results[i];
                  return (
                    <li
                      key={`${f.name}-${i}`}
                      className="px-3 py-2 flex items-baseline justify-between gap-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="font-mono text-[12px] text-ink-deep truncate">
                          {f.name}
                        </div>
                        {r ? (
                          <div className="mt-0.5 text-[11px] text-ink-soft">
                            {r.summary}
                            {r.warnings.length > 0 ? (
                              <span className="ml-1 text-mustard font-mono">
                                · {r.warnings.length} warning
                                {r.warnings.length === 1 ? "" : "s"}
                              </span>
                            ) : null}
                          </div>
                        ) : (
                          <div className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-mute">
                            {f.type || extOf(f.name)} · {fmtSize(f.size)}
                          </div>
                        )}
                      </div>
                      {state !== "parsing" ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            removeFile(i);
                          }}
                          aria-label={`Remove ${f.name}`}
                          className="text-ink-mute hover:text-brick text-[12px] font-mono shrink-0"
                        >
                          ✕
                        </button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}

          {error ? (
            <p className="text-[12px] font-mono text-brick">{error}</p>
          ) : null}
        </div>

        <div className="px-5 py-3 border-t border-hairline flex items-center justify-between">
          <span className="text-[11px] font-mono uppercase tracking-[0.1em] text-ink-mute">
            {state === "parsing"
              ? "Parsing…"
              : state === "ready"
              ? "Ready to apply"
              : files.length === 0
              ? "Pick files to begin"
              : "Press Parse to extract"}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={close}
              className="text-[12px] font-medium px-3 py-1.5 text-ink-soft hover:text-ink rounded-sm transition-colors"
            >
              Cancel
            </button>
            {state === "ready" ? (
              <button
                type="button"
                onClick={apply}
                disabled={results.length === 0}
                className="text-[12px] font-medium px-3 py-1.5 bg-ink-deep text-paper hover:bg-ink rounded-sm transition-colors disabled:opacity-30"
              >
                Use as brief
              </button>
            ) : (
              <button
                type="button"
                onClick={parseAll}
                disabled={files.length === 0 || state === "parsing"}
                className="text-[12px] font-medium px-3 py-1.5 bg-ink-deep text-paper hover:bg-ink rounded-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {state === "parsing" ? "Parsing…" : "Parse"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function extOf(name: string): string {
  if (!name.includes(".")) return "file";
  return name.split(".").pop()?.toLowerCase() || "file";
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
