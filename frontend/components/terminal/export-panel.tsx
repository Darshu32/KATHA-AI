"use client";

import { useState } from "react";
import { Download, FileText, FileSpreadsheet, Boxes, Layers, Cpu, Wrench } from "lucide-react";

import api from "@/lib/api-client";
import { useAuthStore, useDesignStore } from "@/lib/store";
import type { ExportFormat } from "@/lib/types";

type FormatMeta = {
  id: ExportFormat;
  label: string;
  description: string;
  group: "document" | "cad" | "specialist";
  icon: typeof FileText;
};

const FORMATS: FormatMeta[] = [
  { id: "pdf", label: "PDF Dossier", description: "Print-ready multi-section dossier", group: "document", icon: FileText },
  { id: "docx", label: "Word Spec", description: "Editable spec document for client review", group: "document", icon: FileText },
  { id: "xlsx", label: "Excel Schedule", description: "4 sheets: summary, materials, cost, MEP", group: "document", icon: FileSpreadsheet },
  { id: "dxf", label: "DXF Floor Plan", description: "AutoCAD R2010, layered plan", group: "cad", icon: Layers },
  { id: "obj", label: "Wavefront OBJ", description: "Zip with .obj + .mtl, for Blender / Rhino", group: "cad", icon: Boxes },
  { id: "gltf", label: "glTF 2.0", description: "Web 3D, opens in three.js / Blender", group: "cad", icon: Boxes },
  { id: "ifc", label: "IFC 4 (BIM)", description: "Opens in Revit / ArchiCAD / BIMVision", group: "specialist", icon: Cpu },
  { id: "step", label: "STEP AP214", description: "CAD exchange, FreeCAD / Fusion / SolidWorks", group: "specialist", icon: Cpu },
  { id: "gcode", label: "G-code Contours", description: "CNC starting point (6mm end mill default)", group: "specialist", icon: Wrench },
];

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ExportPanel() {
  const { activeGraph, activeProjectId } = useDesignStore();
  const token = useAuthStore((s) => s.token);

  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastDownloaded, setLastDownloaded] = useState<string | null>(null);

  const run = async (fmt: ExportFormat) => {
    if (!token) {
      setError("Sign in to download exports.");
      return;
    }
    setBusy(fmt);
    setError(null);
    try {
      const { blob, filename } = await api.design.exportFile(token, activeProjectId, fmt);
      download(blob, filename);
      setLastDownloaded(filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Export '${fmt}' failed`);
    } finally {
      setBusy(null);
    }
  };

  if (!activeGraph) {
    return (
      <div className="p-4 text-[11px]" style={{ color: "var(--ink-3)" }}>
        Generate a design to enable export.
      </div>
    );
  }

  const groups: Array<[string, FormatMeta["group"]]> = [
    ["Documents", "document"],
    ["CAD / 3D", "cad"],
    ["BIM / Specialist", "specialist"],
  ];

  return (
    <div className="h-full flex flex-col" style={{ backgroundColor: "var(--paper)" }}>
      <div
        className="flex items-center justify-between px-3 py-2"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
          9 export formats · project <span style={{ color: "var(--ink)" }}>{activeProjectId}</span>
        </span>
        {lastDownloaded && (
          <span className="text-[10px]" style={{ color: "#3a6a7a" }}>
            Last: {lastDownloaded}
          </span>
        )}
      </div>

      {error && (
        <div
          className="px-3 py-2 text-[11px]"
          style={{ color: "#b14a2c", borderBottom: "1px solid var(--rule)" }}
        >
          {error}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto">
        {groups.map(([label, groupId]) => {
          const items = FORMATS.filter((f) => f.group === groupId);
          return (
            <section key={groupId}>
              <div
                className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-semibold"
                style={{
                  color: "var(--ink-3)",
                  backgroundColor: "var(--paper-deep, #ece5d8)",
                  borderBottom: "1px solid var(--rule)",
                }}
              >
                {label}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-0">
                {items.map((f) => {
                  const Icon = f.icon;
                  const isBusy = busy === f.id;
                  return (
                    <button
                      key={f.id}
                      onClick={() => run(f.id)}
                      disabled={!!busy}
                      className="flex items-start gap-2 text-left px-3 py-2 transition-colors"
                      style={{
                        borderBottom: "1px solid var(--rule)",
                        borderRight: "1px solid var(--rule)",
                        backgroundColor: isBusy ? "var(--paper-deep, #ece5d8)" : "transparent",
                        opacity: busy && !isBusy ? 0.5 : 1,
                      }}
                    >
                      <Icon size={14} style={{ color: "var(--ink)", marginTop: 2 }} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] font-semibold" style={{ color: "var(--ink)" }}>
                            {f.label}
                          </span>
                          <span className="text-[9px] uppercase" style={{ color: "var(--ink-4)" }}>
                            .{f.id}
                          </span>
                        </div>
                        <div className="text-[10px] mt-0.5" style={{ color: "var(--ink-3)" }}>
                          {isBusy ? "Downloading…" : f.description}
                        </div>
                      </div>
                      <Download size={12} style={{ color: "var(--ink-3)", marginTop: 4 }} />
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
