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
    setError(null);
    onClose();
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

        <div className="max-h-[60vh] overflow-y-auto draft-scroll">
          {state === "loading" ? (
            <div className="px-5 py-5 font-mono text-[12px] text-ink-mute">
              Loading projects…
            </div>
          ) : state === "error" ? (
            <div className="px-5 py-5 text-[12px] font-mono text-brick">
              {error}
            </div>
          ) : projects.length === 0 ? (
            <div className="px-5 py-5 text-[13px] text-ink-soft">
              No projects yet. Click <span className="font-medium">New project</span> above to start one.
            </div>
          ) : (
            <ul className="divide-y divide-hairline">
              {projects.map((p) => {
                const active = p.id === activeProjectId;
                const renaming = renamingId === p.id;
                return (
                  <li
                    key={p.id}
                    className={`px-5 py-3 flex items-baseline gap-3 group ${
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
                        className="flex-1 text-left flex items-baseline gap-2 disabled:opacity-50 disabled:cursor-wait"
                      >
                        {active ? (
                          <span className="text-pencil text-[10px]" aria-hidden>
                            ●
                          </span>
                        ) : null}
                        <span className="text-[13px] text-ink-deep font-medium truncate">
                          {p.name}
                          {openingId === p.id ? (
                            <span className="ml-2 font-mono text-[10px] text-ink-mute">
                              opening…
                            </span>
                          ) : null}
                        </span>
                      </button>
                    )}
                    <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-mute tnum shrink-0">
                      {formatRelative(p.updated_at)}
                    </span>
                    <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-2 shrink-0">
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
                        onClick={() => void archiveProject(p)}
                        className="text-ink-mute hover:text-brick text-[11px] font-mono"
                        aria-label={`Archive ${p.name}`}
                      >
                        Archive
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {state === "ready" && error ? (
          <div className="px-5 py-2 border-t border-hairline text-[12px] font-mono text-brick">
            {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Coarse human-friendly relative time. Falls back to date for >1 week. */
function formatRelative(iso: string): string {
  const now = Date.now();
  const t = new Date(iso).getTime();
  if (!t) return "—";
  const diff = Math.max(0, now - t);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "just now";
  if (diff < hour) return `${Math.floor(diff / minute)}m ago`;
  if (diff < day) return `${Math.floor(diff / hour)}h ago`;
  if (diff < 7 * day) return `${Math.floor(diff / day)}d ago`;
  return new Date(iso).toLocaleDateString();
}
