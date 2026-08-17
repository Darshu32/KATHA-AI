"use client";

/* ProjectPicker — the workspace's project-management surface.
 *
 * Before this lived: once an architect generated a design, they were
 * stuck on that project. No way to open a previous one, switch
 * between drafts, rename, or archive. This modal closes that gap:
 *
 *   • List every non-archived project the user owns, newest-first.
 *   • Click a row → load that project's latest version into the
 *     gallery (graph + render via /projects/{id}/latest).
 *   • Inline-rename a project name (PATCH /projects/{id}).
 *   • Archive a project (PATCH status=archived, hides from the list).
 *   • "New project" creates an empty project and clears the gallery
 *     so the next generation starts fresh.
 *
 * v2 would add: version-history scrubbing across reopened projects,
 * description editing, project search, and project-type filtering.
 * For prototype: list + open + rename + archive + new.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  design as designApi,
  projects as projectsApi,
  type ProjectOut,
} from "@/lib/api-client";

type DialogState = "loading" | "ready" | "error";

export interface OpenedProject {
  projectId: string;
  version: number;
  graphData: unknown;
  imageUrl: string | null;
  prompt: string | null;
  projectName: string;
  objectsBbox: Array<{ id: string; name: string; type: string; x: number; y: number; w: number; h: number }>;
}

export function ProjectPicker({
  open,
  onClose,
  onOpenProject,
  onNewProject,
  activeProjectId,
  token,
}: {
  open: boolean;
  onClose: () => void;
  /** Called when the architect opens an existing project. The
   *  workspace replaces its in-memory state with this version. */
  onOpenProject: (project: OpenedProject) => void;
  /** Called when the architect creates a fresh project. Workspace
   *  clears generations + resets activeProjectId, leaving the
   *  prompt input empty and ready for the first Generate. */
  onNewProject: () => void;
  activeProjectId: string | null;
  token: string | undefined;
}) {
  const [state, setState] = useState<DialogState>("loading");
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [openingId, setOpeningId] = useState<string | null>(null);
  // Two-step archive — single-click feels destructive; a 4-second
  // confirmation window prevents accidental loss of a project the
  // architect has spent days on. Reset on close + on commit.
  const [confirmArchiveId, setConfirmArchiveId] = useState<string | null>(null);
  // Free-text filter over project names — a switcher this long needs search.
  const [query, setQuery] = useState("");

  const loadProjects = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const res = await projectsApi.list(token);
      // Filter out archived rows + sort newest-first.
      const visible = res.projects
        .filter((p) => p.status !== "archived")
        .sort(
          (a, b) =>
            new Date(b.updated_at).getTime() -
            new Date(a.updated_at).getTime(),
        );
      setProjects(visible);
      setState("ready");
    } catch (e) {
      setState("error");
      if (e instanceof ApiError) {
        setError(`Project list failed (${e.status}).`);
      } else {
        setError("Couldn't reach the backend. Is uvicorn running on :8000?");
      }
    }
  }, [token]);

  useEffect(() => {
    if (open) void loadProjects();
  }, [open, loadProjects]);

  const closeAndReset = () => {
    setRenamingId(null);
    setRenameValue("");
    setConfirmArchiveId(null);
    setQuery("");
    setError(null);
    onClose();
  };

  // Two-step archive flow:
  //   first click  → setConfirmArchiveId(p.id); the row swaps to
  //                  "Archive?" + "Yes" / "Cancel" affordances
  //   second click on Yes → actually fires archiveProject(p)
  //   click anywhere else → clears confirm state via row-specific
  //                          onMouseLeave or explicit Cancel
  const requestArchive = (p: ProjectOut) => {
    if (confirmArchiveId === p.id) {
      void archiveProject(p);
      setConfirmArchiveId(null);
    } else {
      setConfirmArchiveId(p.id);
    }
  };

  const openProject = async (p: ProjectOut) => {
    if (openingId) return;
    setOpeningId(p.id);
    setError(null);
    try {
      const latest = await designApi.getLatest(token, p.id);
      onOpenProject({
        projectId: p.id,
        version: latest.version,
        graphData: latest.graph_data,
        imageUrl: latest.image_url,
        prompt: latest.prompt,
        projectName: p.name,
        objectsBbox: latest.objects_bbox ?? [],
      });
      closeAndReset();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 404) {
          // Project exists but has no generated versions yet — still a
          // valid "open" outcome; just clear the gallery and treat it
          // as a fresh slate scoped to this project.
          onOpenProject({
            projectId: p.id,
            version: 0,
            graphData: null,
            imageUrl: null,
            prompt: null,
            projectName: p.name,
            objectsBbox: [],
          });
          closeAndReset();
          return;
        }
        setError(`Couldn't open '${p.name}' (${e.status}).`);
      } else {
        setError(`Couldn't reach the backend to open '${p.name}'.`);
      }
    } finally {
      setOpeningId(null);
    }
  };

  const submitRename = async (p: ProjectOut) => {
    const next = renameValue.trim();
    if (!next || next === p.name) {
      setRenamingId(null);
      return;
    }
    setError(null);
    try {
      const updated = await projectsApi.update(token, p.id, { name: next });
      setProjects((rows) =>
        rows.map((r) => (r.id === p.id ? updated : r)),
      );
      setRenamingId(null);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Rename failed (${e.status}).`);
      } else {
        setError("Couldn't reach the backend to rename.");
      }
    }
  };

  const archiveProject = async (p: ProjectOut) => {
    setError(null);
    try {
      await projectsApi.update(token, p.id, { status: "archived" });
      // Remove locally — the next list refresh would do the same.
      setProjects((rows) => rows.filter((r) => r.id !== p.id));
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Archive failed (${e.status}).`);
      } else {
        setError("Couldn't reach the backend to archive.");
      }
    }
  };

  // Filter by name, then group by recency (Today / Previous 7 days / …) —
  // `projects` is already sorted newest-first, so each bucket stays ordered.
  const q = query.trim().toLowerCase();
  const filtered = q
    ? projects.filter((p) => p.name.toLowerCase().includes(q))
    : projects;
  const buckets: Record<string, ProjectOut[]> = {};
  for (const p of filtered) {
    (buckets[recencyBucket(p.updated_at)] ??= []).push(p);
  }
  const groups = RECENCY_ORDER.filter((label) => buckets[label]?.length).map(
    (label) => ({ label, rows: buckets[label] }),
  );

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Projects"
      className="fixed inset-0 z-40 flex items-start justify-center pt-20 px-4"
      onKeyDown={(e) => {
        if (e.key === "Escape") closeAndReset();
      }}
    >
      <div
        className="absolute inset-0 bg-ink-deep/30"
        onClick={closeAndReset}
        aria-hidden="true"
      />
      <div className="relative w-full max-w-xl bg-paper border border-graphite rounded-md shadow-card overflow-hidden">
        <div className="px-5 py-3 border-b border-hairline flex items-baseline justify-between">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-mute">
              Projects
            </span>
            <h2 className="mt-1 text-[16px] text-ink-deep font-semibold tracking-[-0.01em]">
              Open or switch a project
            </h2>
          </div>
          <button
            type="button"
            onClick={closeAndReset}
            aria-label="Close project picker"
            className="text-ink-mute hover:text-ink text-[14px] font-mono p-1"
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-3 border-b border-hairline">
          <button
            type="button"
            onClick={() => {
              onNewProject();
              closeAndReset();
            }}
            className="w-full text-left flex items-baseline gap-2 px-3 py-2 border border-hairline rounded-sm hover:border-graphite hover:bg-paper-soft transition-colors"
          >
            <span className="text-pencil text-[14px] leading-none">+</span>
            <span className="text-[13px] text-ink-deep font-medium">
              New project
            </span>
            <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">
              start fresh
            </span>
          </button>
        </div>

        {/* Search — a switcher with this many projects needs a filter. */}
        {state === "ready" && projects.length > 6 ? (
          <div className="px-5 py-2.5 border-b border-hairline">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search projects…"
              aria-label="Search projects"
              className="w-full bg-paper-soft border border-hairline rounded-sm px-3 py-1.5 text-[13px] text-ink-deep placeholder:text-ink-mute outline-none focus:border-graphite focus:bg-paper transition-colors"
            />
          </div>
        ) : null}

        <div className="max-h-[54vh] overflow-y-auto draft-scroll">
          {state === "loading" ? (
            <div className="px-5 py-6 font-mono text-[12px] text-ink-mute">
              Loading projects…
            </div>
          ) : state === "error" ? (
            <div className="px-5 py-6 text-[12px] font-mono text-brick">
              {error}
            </div>
          ) : projects.length === 0 ? (
            <div className="px-5 py-6 text-[13px] text-ink-soft">
              No projects yet. Click <span className="font-medium">New project</span> above to start one.
            </div>
          ) : groups.length === 0 ? (
            <div className="px-5 py-6 text-[13px] text-ink-soft">
              No projects match “<span className="font-medium">{query.trim()}</span>”.
            </div>
          ) : (
            groups.map((group) => (
              <section key={group.label}>
                {/* Recency header — Today / Previous 7 days / … — sticky so the
                    architect keeps their place while scrolling a long history. */}
                <div className="sticky top-0 z-10 bg-paper/95 backdrop-blur-sm px-5 py-1.5 border-b border-hairline flex items-baseline gap-2">
                  <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-mute">
                    {group.label}
                  </span>
                  <span className="font-mono text-[10px] text-ink-mute/60 tnum">
                    {group.rows.length}
                  </span>
                </div>
                <ul className="divide-y divide-hairline">
                  {group.rows.map((p) => {
                    const active = p.id === activeProjectId;
                    const renaming = renamingId === p.id;
                    const typeLabel = titleCase(
                      p.project_sub_type || p.project_scale || p.project_type || "",
                    );
                    return (
                      <li
                        key={p.id}
                        className={`px-5 py-2.5 flex items-center gap-3 group ${
                          active ? "bg-pencil-bg/40" : "hover:bg-paper-soft"
                        }`}
                      >
                        {renaming ? (
                          <input
                            autoFocus
                            type="text"
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") void submitRename(p);
                              if (e.key === "Escape") setRenamingId(null);
                            }}
                            onBlur={() => void submitRename(p)}
                            className="flex-1 outline-none bg-paper border border-graphite rounded-sm px-2 py-1 text-[13px] text-ink-deep"
                          />
                        ) : (
                          <button
                            type="button"
                            onClick={() => void openProject(p)}
                            disabled={!!openingId}
                            className="flex-1 text-left flex items-center gap-2 min-w-0 disabled:opacity-50 disabled:cursor-wait"
                          >
                            {active ? (
                              <span className="text-pencil text-[9px] shrink-0" aria-hidden>
                                ●
                              </span>
                            ) : null}
                            <span className="text-[13px] text-ink-deep font-medium truncate">
                              {p.name}
                            </span>
                            {/* Quiet category chip — title-cased, most-specific
                                available (sub-type › scale › type). Soft so it
                                informs without shouting on every row. */}
                            {typeLabel ? (
                              <span className="text-[10px] text-ink-mute border border-hairline px-1.5 py-[1px] rounded-sm shrink-0 leading-normal">
                                {typeLabel}
                              </span>
                            ) : null}
                            {openingId === p.id ? (
                              <span className="ml-1 font-mono text-[10px] text-ink-mute shrink-0">
                                opening…
                              </span>
                            ) : null}
                          </button>
                        )}
                        <span
                          className="font-mono text-[10.5px] text-ink-mute tnum shrink-0 w-[62px] text-right"
                          title={fullDate(p.updated_at)}
                        >
                          {formatWhen(p.updated_at)}
                        </span>
                        <div
                          className={`flex items-center gap-2 shrink-0 transition-opacity ${
                            confirmArchiveId === p.id
                              ? "opacity-100"
                              : "opacity-0 group-hover:opacity-100"
                          }`}
                        >
                          {confirmArchiveId === p.id ? (
                            <>
                              <span className="font-mono text-[10px] uppercase tracking-tagged text-brick">
                                Archive?
                              </span>
                              <button
                                type="button"
                                onClick={() => requestArchive(p)}
                                className="text-[11px] font-mono text-brick hover:underline"
                                aria-label={`Confirm archive ${p.name}`}
                              >
                                Yes
                              </button>
                              <button
                                type="button"
                                onClick={() => setConfirmArchiveId(null)}
                                className="text-[11px] font-mono text-ink-mute hover:text-ink"
                                aria-label="Cancel archive"
                              >
                                Cancel
                              </button>
                            </>
                          ) : (
                            <>
                              {!renaming ? (
                                <button
                                  type="button"
                                  onClick={() => {
                                    setRenamingId(p.id);
                                    setRenameValue(p.name);
                                  }}
                                  className="text-ink-mute hover:text-ink text-[11px] font-mono"
                                  aria-label={`Rename ${p.name}`}
                                >
                                  Rename
                                </button>
                              ) : null}
                              <button
                                type="button"
                                onClick={() => requestArchive(p)}
                                className="text-ink-mute hover:text-brick text-[11px] font-mono"
                                aria-label={`Archive ${p.name}`}
                              >
                                Archive
                              </button>
                            </>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))
          )}
        </div>

        {state === "ready" ? (
          <div className="px-5 py-2 border-t border-hairline flex items-baseline justify-between gap-3 font-mono text-[10.5px] text-ink-mute">
            {error ? (
              <span className="text-brick truncate">{error}</span>
            ) : (
              <span className="tnum">
                {projects.length} project{projects.length === 1 ? "" : "s"}
                {q && filtered.length !== projects.length
                  ? ` · ${filtered.length} shown`
                  : ""}
              </span>
            )}
            <span className="text-ink-mute/60 shrink-0">Hover a row to rename or archive</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

const RECENCY_ORDER = ["Today", "Previous 7 days", "Previous 30 days", "Earlier"];

/** Which recency section a timestamp belongs to (by elapsed time). */
function recencyBucket(iso: string): string {
  const t = new Date(iso).getTime();
  if (!t) return "Earlier";
  const diff = Date.now() - t;
  const day = 86_400_000;
  if (diff < day) return "Today";
  if (diff < 7 * day) return "Previous 7 days";
  if (diff < 30 * day) return "Previous 30 days";
  return "Earlier";
}

/** Compact, unambiguous "last edited": relative within a week, then a clear
 *  "7 Aug" / "7 Aug 2026" — never a locale-ambiguous 07/08/2026. */
function formatWhen(iso: string): string {
  const t = new Date(iso).getTime();
  if (!t) return "—";
  const diff = Math.max(0, Date.now() - t);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "just now";
  if (diff < hour) return `${Math.floor(diff / minute)}m ago`;
  if (diff < day) return `${Math.floor(diff / hour)}h ago`;
  if (diff < 7 * day) return `${Math.floor(diff / day)}d ago`;
  const d = new Date(iso);
  const opts: Intl.DateTimeFormatOptions =
    d.getFullYear() === new Date().getFullYear()
      ? { day: "numeric", month: "short" }
      : { day: "numeric", month: "short", year: "numeric" };
  return d.toLocaleDateString("en-GB", opts);
}

/** Full timestamp for the row's hover tooltip. */
function fullDate(iso: string): string {
  const t = new Date(iso).getTime();
  if (!t) return "";
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "residential" → "Residential"; "walk_in" → "Walk In". */
function titleCase(s: string): string {
  return s
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
