"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import api, { type ProjectResponse } from "../../lib/api-client";
import { useProjectStore } from "../../lib/store";

export default function DashboardPage() {
  const projects = useProjectStore((s) => s.projects);
  const setProjects = useProjectStore((s) => s.setProjects);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.projects
      .list()
      .then((res) => {
        setProjects(
          res.projects.map((p: ProjectResponse) => ({
            id: p.id,
            name: p.name,
            description: p.description,
            status: p.status,
            latestVersion: p.latest_version,
            createdAt: p.created_at,
            updatedAt: p.updated_at,
          })),
        );
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [setProjects]);

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-3xl text-ink">Projects</h1>
          <p className="mt-1 text-ink/60">Your architecture design projects</p>
        </div>
        <Link
          href="/project/new"
          className="rounded-xl bg-ink px-5 py-2.5 font-medium text-white transition-colors hover:bg-ink/90"
        >
          New Project
        </Link>
      </div>

      {loading ? (
        <div className="mt-16 text-center text-ink/40">Loading projects...</div>
      ) : error ? (
        <div className="mt-16 text-center text-red-600">{error}</div>
      ) : projects.length === 0 ? (
        <div className="mt-16 text-center">
          <p className="text-ink/40">No projects yet.</p>
          <Link
            href="/project/new"
            className="mt-4 inline-block rounded-xl bg-clay px-6 py-2.5 font-medium text-white"
          >
            Create your first design
          </Link>
        </div>
      ) : (
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/project/${project.id}`}
              className="group rounded-2xl border border-black/10 bg-white/60 p-5 shadow-panel transition-shadow hover:shadow-lg"
            >
              <div className="flex items-start justify-between">
                <h3 className="font-display text-lg text-ink group-hover:text-clay">
                  {project.name}
                </h3>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                    project.status === "ready"
                      ? "bg-emerald-100 text-emerald-700"
                      : project.status === "generating"
                        ? "bg-amber-100 text-amber-700"
                        : "bg-gray-100 text-gray-600"
                  }`}
                >
                  {project.status}
                </span>
              </div>
              {project.description && (
                <p className="mt-2 line-clamp-2 text-sm text-ink/60">
                  {project.description}
                </p>
              )}
              <div className="mt-3 flex items-center gap-3 text-xs text-ink/40">
                <span>v{project.latestVersion}</span>
                <span>{new Date(project.updatedAt).toLocaleDateString()}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
