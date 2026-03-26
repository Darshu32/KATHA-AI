"use client";

import { useState } from "react";
import { useDesignGraphStore } from "../lib/store";

interface ObjectInspectorProps {
  onEditSubmit: (objectId: string, prompt: string) => void;
  isLoading?: boolean;
}

export default function ObjectInspector({
  onEditSubmit,
  isLoading,
}: ObjectInspectorProps) {
  const graphData = useDesignGraphStore((s) => s.graphData);
  const selectedObjectId = useDesignGraphStore((s) => s.selectedObjectId);
  const selectObject = useDesignGraphStore((s) => s.selectObject);
  const [editPrompt, setEditPrompt] = useState("");

  const objects = (graphData?.objects as Array<Record<string, unknown>>) ?? [];
  const selectedObj = objects.find((o) => o.id === selectedObjectId);

  if (!selectedObj) {
    return (
      <div className="rounded-2xl border border-black/10 bg-white/60 p-4">
        <p className="text-sm text-ink/40">
          Click an object in the 3D view to inspect and edit it.
        </p>
      </div>
    );
  }

  const dims = selectedObj.dimensions as Record<string, number> | undefined;
  const pos = selectedObj.position as Record<string, number> | undefined;
  const color =
    typeof selectedObj.color === "string" ? selectedObj.color : undefined;

  const handleEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editPrompt.trim() || !selectedObjectId) return;
    onEditSubmit(selectedObjectId, editPrompt.trim());
    setEditPrompt("");
  };

  return (
    <div className="space-y-3 rounded-2xl border border-black/10 bg-white/60 p-4">
      <div className="flex items-center justify-between">
        <h4 className="font-display text-base text-ink">
          {(selectedObj.name as string) || (selectedObj.type as string)}
        </h4>
        <button
          onClick={() => selectObject(null)}
          className="text-xs text-ink/40 hover:text-ink"
        >
          Deselect
        </button>
      </div>

      {/* Properties */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg bg-sand/50 px-2 py-1.5">
          <span className="text-ink/50">Type</span>
          <p className="font-medium text-ink">{selectedObj.type as string}</p>
        </div>
        <div className="rounded-lg bg-sand/50 px-2 py-1.5">
          <span className="text-ink/50">Material</span>
          <p className="font-medium text-ink">
            {(selectedObj.material as string) || "—"}
          </p>
        </div>
        {dims && (
          <div className="col-span-2 rounded-lg bg-sand/50 px-2 py-1.5">
            <span className="text-ink/50">Dimensions</span>
            <p className="font-medium text-ink">
              {dims.length ?? 0} x {dims.width ?? 0} x {dims.height ?? 0}
            </p>
          </div>
        )}
        {pos && (
          <div className="col-span-2 rounded-lg bg-sand/50 px-2 py-1.5">
            <span className="text-ink/50">Position</span>
            <p className="font-medium text-ink">
              ({pos.x?.toFixed(1)}, {pos.y?.toFixed(1)}, {pos.z?.toFixed(1)})
            </p>
          </div>
        )}
        {color && (
          <div className="rounded-lg bg-sand/50 px-2 py-1.5">
            <span className="text-ink/50">Color</span>
            <div className="mt-1 flex items-center gap-1.5">
              <div
                className="h-4 w-4 rounded-full border border-black/10"
                style={{ backgroundColor: color }}
              />
              <span className="font-medium text-ink">{color}</span>
            </div>
          </div>
        )}
      </div>

      {/* Prompt-based edit */}
      <form onSubmit={handleEdit} className="space-y-2">
        <label className="block text-xs font-medium text-ink/60">
          Edit via prompt
        </label>
        <textarea
          value={editPrompt}
          onChange={(e) => setEditPrompt(e.target.value)}
          placeholder="Change this to exposed brick finish..."
          rows={2}
          className="w-full resize-none rounded-lg border border-black/10 bg-white/80 px-3 py-2 text-sm text-ink placeholder:text-ink/30 focus:outline-none focus:ring-2 focus:ring-clay/20"
          disabled={isLoading}
        />
        <button
          type="submit"
          disabled={!editPrompt.trim() || isLoading}
          className="w-full rounded-lg bg-clay px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-clay/90 disabled:opacity-50"
        >
          {isLoading ? "Applying..." : "Apply Edit"}
        </button>
      </form>
    </div>
  );
}
