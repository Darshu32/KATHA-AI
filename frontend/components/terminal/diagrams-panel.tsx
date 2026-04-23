"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";

import api from "@/lib/api-client";
import { useAuthStore, useDesignStore } from "@/lib/store";
import type { DiagramPayload } from "@/lib/types";

export default function DiagramsPanel() {
  const { activeGraph, activeProjectId } = useDesignStore();
  const token = useAuthStore((s) => s.token);

  const [diagrams, setDiagrams] = useState<DiagramPayload[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const fetchAll = async () => {
    if (!token) {
      setError("Sign in to generate diagrams.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.design.generateDiagrams(token, activeProjectId);
      setDiagrams(res.diagrams);
      if (!selected && res.diagrams[0]?.id) setSelected(res.diagrams[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Diagrams request failed");
    } finally {
      setLoading(false);
    }
  };

  if (!activeGraph) {
    return (
      <div className="p-4 text-[11px]" style={{ color: "var(--ink-3)" }}>
        Generate a design to render auto-diagrams.
      </div>
    );
  }

  const active = diagrams.find((d) => d.id === selected) ?? diagrams[0];

  return (
    <div className="h-full flex" style={{ backgroundColor: "var(--paper)" }}>
      <div
        className="w-40 flex-shrink-0 flex flex-col"
        style={{ borderRight: "1px solid var(--rule)" }}
      >
        <div
          className="px-3 py-2 flex items-center justify-between"
          style={{ borderBottom: "1px solid var(--rule)" }}
        >
          <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--ink-3)" }}>
            8 diagrams
          </span>
          <button
            onClick={fetchAll}
            disabled={loading}
            className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded"
            style={{ border: "1px solid var(--rule)", color: "var(--ink)" }}
            title="Generate all"
          >
            <RefreshCw size={10} className={loading ? "animate-spin" : ""} />
            {diagrams.length ? "Refresh" : "Generate"}
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          {diagrams.length === 0 && !loading && (
            <div className="p-3 text-[11px]" style={{ color: "var(--ink-4)" }}>
              Click Generate to render the 8 BRD auto-diagrams for this design.
            </div>
          )}
          {diagrams.map((d) => (
            <button
              key={d.id}
              onClick={() => setSelected(d.id)}
              className="w-full text-left px-3 py-2 text-[11px]"
              style={{
                borderBottom: "1px solid var(--rule)",
                backgroundColor: d.id === active?.id ? "var(--paper-deep, #ece5d8)" : "transparent",
                color: "var(--ink)",
                fontWeight: d.id === active?.id ? 600 : 400,
              }}
            >
              {d.name}
              {d.error && (
                <div className="text-[10px] mt-0.5" style={{ color: "#b14a2c" }}>
                  error
                </div>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-w-0 overflow-auto p-3 flex items-start justify-center">
        {error && <div className="text-[11px]" style={{ color: "#b14a2c" }}>{error}</div>}
        {!error && !active && !loading && (
          <div className="text-[11px]" style={{ color: "var(--ink-3)" }}>
            No diagram selected.
          </div>
        )}
        {!error && active?.svg && (
          <div
            className="w-full"
            style={{ maxWidth: 1100 }}
            dangerouslySetInnerHTML={{ __html: active.svg }}
          />
        )}
        {!error && active && !active.svg && (
          <div className="text-[11px]" style={{ color: "#b14a2c" }}>
            {active.error ?? "This diagram could not be rendered."}
          </div>
        )}
      </div>
    </div>
  );
}
