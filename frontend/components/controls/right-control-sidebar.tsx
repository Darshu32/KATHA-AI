"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Layers,
  Sun,
  Download,
  PanelRightClose,
  LayoutGrid,
  Paintbrush,
  ChevronDown,
  Camera,
  Palette,
} from "lucide-react";
import { useImageGenStore, useDesignStore } from "@/lib/store";
import { LAYOUT_PRESETS, getMockGraphForPreset } from "@/lib/mock-design-graph";
import { design as designApi } from "@/lib/api-client";
import { exportActiveView, type ExportFormat } from "@/lib/canvas-export";
import type { ArchTheme, CameraMode, DesignGraph, LightingMode } from "@/lib/types";
import ModeSwitcher2D3D from "./mode-switcher-2d3d";

interface RightControlSidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

const THEMES: { id: ArchTheme; label: string; swatch: string }[] = [
  { id: "modern", label: "Modern", swatch: "#D9D4C7" },
  { id: "contemporary", label: "Contemporary", swatch: "#C0B9A8" },
  { id: "minimalist", label: "Minimalist", swatch: "#EDEAE1" },
  { id: "traditional", label: "Traditional", swatch: "#D4B58C" },
  { id: "rustic", label: "Rustic", swatch: "#B8824A" },
  { id: "industrial", label: "Industrial", swatch: "#8A8580" },
  { id: "scandinavian", label: "Scandinavian", swatch: "#EFEBE0" },
  { id: "luxury", label: "Luxury", swatch: "#C9A96E" },
];

const CAMERAS: { id: CameraMode; label: string }[] = [
  { id: "front", label: "Front" },
  { id: "aerial", label: "Aerial" },
  { id: "interior", label: "Interior" },
  { id: "eye-level", label: "Eye-level" },
];

const LIGHTINGS: { id: LightingMode; label: string }[] = [
  { id: "daylight", label: "Daylight" },
  { id: "golden-hour", label: "Golden hour" },
  { id: "night", label: "Night" },
  { id: "overcast", label: "Overcast" },
];

export default function RightControlSidebar({ isOpen, onClose }: RightControlSidebarProps) {
  const { theme, setTheme, camera, setCamera, lighting, setLighting, prompt, viewMode, ratio, quality, drawingType, setPrompt } = useImageGenStore();
  const { activeGraph, setActiveGraph, setLoading, setEstimate, layerVisibility, setLayerVisibility } = useDesignStore();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const [activeLayoutId, setActiveLayoutId] = useState<string | null>(null);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [exportMsg, setExportMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const handleExport = async (fmt: ExportFormat) => {
    if (exporting) return;
    if (!activeGraph) {
      setExportMsg({ ok: false, text: "Generate a design first." });
      setTimeout(() => setExportMsg(null), 2500);
      return;
    }
    setExporting(fmt);
    const res = await exportActiveView(fmt);
    setExportMsg(res.ok ? { ok: true, text: `${fmt} downloaded` } : { ok: false, text: res.reason || `${fmt} failed` });
    setTimeout(() => setExportMsg(null), 2800);
    setExporting(null);
  };

  const currentTheme = THEMES.find((t) => t.id === theme) ?? THEMES[0];

  const handleLayoutPreset = async (presetId: string) => {
    const preset = LAYOUT_PRESETS.find((p) => p.id === presetId);
    if (!preset) return;
    setActiveLayoutId(presetId);
    setLoading(true);

    const basePrompt = prompt.trim() ||
      `${preset.description}. ${preset.rooms}. Target area ${preset.sqftRange} sqft.`;

    // Seed the prompt input so the user sees what was sent.
    if (!prompt.trim()) setPrompt(basePrompt);

    try {
      const result = await designApi.generate("", "demo", {
        prompt: basePrompt,
        room_type: preset.roomType,
        style: theme,
        camera,
        lighting,
        view_mode: viewMode,
        ratio,
        quality,
        drawing_type: drawingType,
        dimensions: { length: preset.dims.length, width: preset.dims.width },
      });
      if (result?.graph_data) {
        setActiveGraph(result.graph_data as unknown as DesignGraph);
        setEstimate((result as { estimate?: unknown }).estimate as never);
      } else {
        throw new Error("No graph data");
      }
    } catch {
      setActiveGraph(getMockGraphForPreset(presetId));
      setEstimate(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.aside
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 280, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="h-full flex flex-col overflow-hidden flex-shrink-0"
          style={{
            backgroundColor: "var(--paper)",
            borderLeft: "1px solid var(--rule)",
            fontFamily: "var(--sans)",
            color: "var(--ink)",
          }}
        >
          {/* Header */}
          <div
            className="flex items-center justify-between px-4 h-12"
            style={{ borderBottom: "1px solid var(--rule)", flexShrink: 0 }}
          >
            <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: "-0.005em" }}>
              Parameters
            </span>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md transition-colors"
              style={{ color: "var(--ink-3)" }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "var(--ink)";
                e.currentTarget.style.backgroundColor = "var(--paper-2)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "var(--ink-3)";
                e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              <PanelRightClose size={15} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto chat-scrollbar px-4 py-4 space-y-5">
            {/* View mode */}
            <Field label="View">
              <ModeSwitcher2D3D />
            </Field>

            {/* Theme — single row picker */}
            <Field label="Theme">
              <div className="relative">
                <button
                  onClick={() => setThemeOpen((v) => !v)}
                  className="w-full flex items-center gap-2 pl-2.5 pr-2 py-2 rounded-lg transition-colors"
                  style={{
                    border: "1px solid var(--rule)",
                    backgroundColor: "#fff",
                    fontSize: 13,
                  }}
                >
                  <span
                    className="w-3.5 h-3.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: currentTheme.swatch, border: "1px solid var(--rule)" }}
                  />
                  <span className="flex-1 text-left" style={{ color: "var(--ink)", fontWeight: 500 }}>
                    {currentTheme.label}
                  </span>
                  <ChevronDown
                    size={13}
                    className={`transition-transform ${themeOpen ? "rotate-180" : ""}`}
                    style={{ color: "var(--ink-3)" }}
                  />
                </button>
                {themeOpen && (
                  <div
                    className="absolute left-0 right-0 top-full mt-1 rounded-lg overflow-hidden z-20"
                    style={{
                      backgroundColor: "#fff",
                      border: "1px solid var(--rule)",
                      boxShadow: "0 10px 30px -12px rgba(17,17,16,0.2)",
                    }}
                  >
                    {THEMES.map((t) => (
                      <button
                        key={t.id}
                        onClick={() => {
                          setTheme(t.id);
                          setThemeOpen(false);
                        }}
                        className="w-full flex items-center gap-2 px-2.5 py-1.5 transition-colors text-left"
                        style={{
                          backgroundColor: t.id === theme ? "var(--paper-2)" : "transparent",
                          fontSize: 12.5,
                          color: "var(--ink-2)",
                        }}
                        onMouseEnter={(e) => {
                          if (t.id !== theme) e.currentTarget.style.backgroundColor = "var(--paper-2)";
                        }}
                        onMouseLeave={(e) => {
                          if (t.id !== theme) e.currentTarget.style.backgroundColor = "transparent";
                        }}
                      >
                        <span
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: t.swatch, border: "1px solid var(--rule)" }}
                        />
                        {t.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </Field>

            {/* Layout */}
            <Field label="Layout">
              <div className="flex flex-wrap gap-1.5">
                {LAYOUT_PRESETS.slice(0, 4).map((p) => {
                  const active = activeLayoutId === p.id || activeGraph?.room.type === p.roomType;
                  return (
                    <button
                      key={p.id}
                      onClick={() => handleLayoutPreset(p.id)}
                      className="px-2.5 py-1.5 rounded-md transition-colors"
                      style={{
                        fontSize: 11.5,
                        fontWeight: 500,
                        backgroundColor: active ? "var(--ink)" : "transparent",
                        color: active ? "var(--paper)" : "var(--ink-2)",
                        border: active ? "1px solid var(--ink)" : "1px solid var(--rule)",
                      }}
                      title={`${p.rooms} · ${p.sqftRange} sqft · ${p.dims.length}×${p.dims.width}`}
                    >
                      {p.label}
                    </button>
                  );
                })}
              </div>
              {activeGraph && (
                <p
                  className="mt-2"
                  style={{ fontSize: 10.5, color: "var(--ink-3)", fontFamily: "var(--mono)", letterSpacing: "0.04em" }}
                >
                  {activeGraph.room.dimensions.length}' × {activeGraph.room.dimensions.width}' · {activeGraph.objects.length} objects
                </p>
              )}
            </Field>

            {/* Advanced — collapsible; everything noisy hides here */}
            <div style={{ borderTop: "1px solid var(--rule)", paddingTop: 14 }}>
              <button
                onClick={() => setAdvancedOpen((v) => !v)}
                className="w-full flex items-center justify-between group"
                style={{ color: "var(--ink-2)" }}
              >
                <span style={{ fontSize: 11, fontFamily: "var(--mono)", letterSpacing: "0.22em", textTransform: "uppercase" }}>
                  Advanced
                </span>
                <ChevronDown
                  size={13}
                  className={`transition-transform ${advancedOpen ? "rotate-180" : ""}`}
                  style={{ color: "var(--ink-3)" }}
                />
              </button>

              <AnimatePresence initial={false}>
                {advancedOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="pt-4 space-y-5">
                      <Field label="Layers" icon={Layers}>
                        <div className="space-y-1">
                          {(
                            [
                              ["furniture", "Furniture"],
                              ["dimensions", "Dimensions"],
                              ["grid", "Grid"],
                              ["wireframe", "Wireframe"],
                            ] as const
                          ).map(([key, label]) => (
                            <div
                              key={key}
                              onClick={() => setLayerVisibility(key, !layerVisibility[key])}
                              className="flex items-center justify-between py-1.5 px-2 rounded-md cursor-pointer transition-colors"
                              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--paper-2)")}
                              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                            >
                              <span style={{ fontSize: 12.5, color: "var(--ink-2)" }}>{label}</span>
                              <div
                                className="w-7 h-4 rounded-full relative transition-colors"
                                style={{ backgroundColor: layerVisibility[key] ? "var(--ink)" : "var(--rule)" }}
                              >
                                <div
                                  className="absolute top-0.5 w-3 h-3 rounded-full shadow-sm transition-transform"
                                  style={{
                                    backgroundColor: "#fff",
                                    transform: layerVisibility[key] ? "translateX(14px)" : "translateX(2px)",
                                  }}
                                />
                              </div>
                            </div>
                          ))}
                        </div>
                      </Field>

                      <Field label="Camera" icon={Camera}>
                        <div className="flex flex-wrap gap-1.5">
                          {CAMERAS.map((c) => (
                            <Chip key={c.id} active={camera === c.id} onClick={() => setCamera(c.id)}>
                              {c.label}
                            </Chip>
                          ))}
                        </div>
                      </Field>

                      <Field label="Lighting" icon={Sun}>
                        <div className="flex flex-wrap gap-1.5">
                          {LIGHTINGS.map((l) => (
                            <Chip key={l.id} active={lighting === l.id} onClick={() => setLighting(l.id)}>
                              {l.label}
                            </Chip>
                          ))}
                        </div>
                      </Field>

                      <Field label="Export" icon={Download}>
                        <div className="grid grid-cols-2 gap-1.5">
                          {(["PNG", "JPEG", "SVG", "PDF"] as ExportFormat[]).map((f) => {
                            const isExporting = exporting === f;
                            return (
                              <button
                                key={f}
                                onClick={() => handleExport(f)}
                                disabled={!!exporting}
                                className="py-1.5 rounded-md transition-colors disabled:opacity-50"
                                style={{
                                  fontSize: 11.5,
                                  fontWeight: 500,
                                  color: "var(--ink-2)",
                                  border: "1px solid var(--rule)",
                                  backgroundColor: "transparent",
                                  fontFamily: "var(--mono)",
                                  letterSpacing: "0.04em",
                                }}
                                onMouseEnter={(e) => {
                                  if (exporting) return;
                                  e.currentTarget.style.backgroundColor = "var(--paper-2)";
                                  e.currentTarget.style.borderColor = "var(--ink-2)";
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.backgroundColor = "transparent";
                                  e.currentTarget.style.borderColor = "var(--rule)";
                                }}
                              >
                                {isExporting ? "…" : f}
                              </button>
                            );
                          })}
                        </div>
                        {exportMsg && (
                          <p
                            className="mt-2"
                            style={{
                              fontSize: 10.5,
                              fontFamily: "var(--mono)",
                              letterSpacing: "0.04em",
                              color: exportMsg.ok ? "#15803d" : "#b45309",
                            }}
                          >
                            {exportMsg.text}
                          </p>
                        )}
                      </Field>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

function Field({
  label,
  icon: Icon,
  children,
}: {
  label: string;
  icon?: typeof Layers;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-2">
        {Icon && <Icon size={11} style={{ color: "var(--ink-3)" }} />}
        <span
          style={{
            fontSize: 10.5,
            fontFamily: "var(--mono)",
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            color: "var(--ink-3)",
          }}
        >
          {label}
        </span>
      </div>
      {children}
    </div>
  );
}

function Chip({
  children,
  active,
  onClick,
}: {
  children: React.ReactNode;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="px-2.5 py-1.5 rounded-md transition-colors"
      style={{
        fontSize: 11.5,
        fontWeight: 500,
        backgroundColor: active ? "var(--ink)" : "transparent",
        color: active ? "var(--paper)" : "var(--ink-2)",
        border: active ? "1px solid var(--ink)" : "1px solid var(--rule)",
      }}
    >
      {children}
    </button>
  );
}
