"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import PromptInput from "../../../components/prompt-input";
import api from "../../../lib/api-client";
import { useAuthStore, useProjectStore } from "../../../lib/store";

export default function NewProjectPage() {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);
  const addProject = useProjectStore((s) => s.addProject);
  const [isLoading, setIsLoading] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async (data: {
    prompt: string;
    roomType: string;
    style: string;
  }) => {
    if (!token) {
      setError("Please sign in first.");
      return;
    }

    const name = projectName.trim() || `${data.style} ${data.roomType}`.replace(/_/g, " ");
    setIsLoading(true);
    setError(null);

    try {
      // Step 1: Create project
      const project = await api.projects.create(token, {
        name,
        prompt: data.prompt,
        room_type: data.roomType,
        style: data.style,
      });

      addProject({
        id: project.id,
        name: project.name,
        description: project.description,
        status: project.status,
        latestVersion: project.latest_version,
        createdAt: project.created_at,
        updatedAt: project.updated_at,
      });

      // Step 2: Trigger generation
      await api.generation.generate(token, project.id, {
        prompt: data.prompt,
        room_type: data.roomType,
        style: data.style,
      });

      // Navigate to project viewer
      router.push(`/project/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="font-display text-3xl text-ink">New Design Project</h1>
      <p className="mt-2 text-ink/60">
        Describe the space you want to design. The AI will generate a structured
        design graph, 3D scene, and material estimate.
      </p>

      <div className="mt-8 space-y-6">
        {/* Project name */}
        <div>
          <label className="mb-1.5 block text-sm font-medium text-ink/70">
            Project name (optional)
          </label>
          <input
            type="text"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            placeholder="My Living Room Redesign"
            className="w-full rounded-xl border border-black/10 bg-white/80 px-4 py-2.5 text-ink placeholder:text-ink/40 focus:border-clay/50 focus:outline-none focus:ring-2 focus:ring-clay/20"
          />
        </div>

        <PromptInput onSubmit={handleGenerate} isLoading={isLoading} />

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </div>
    </main>
  );
}
