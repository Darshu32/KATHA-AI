"use client";

import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Terminal,
  ChevronUp,
  ChevronDown,
  Calculator,
  ShieldCheck,
  LayoutDashboard,
  FileText,
  Download,
} from "lucide-react";
import { useDesignStore } from "@/lib/store";
import ValidationPanel from "./validation-panel";
import DiagramsPanel from "./diagrams-panel";
import SpecsPanel from "./specs-panel";
import ExportPanel from "./export-panel";

interface EstimationTerminalShellProps {
  isOpen: boolean;
  onToggle: () => void;
}

type TabId = "estimation" | "validation" | "diagrams" | "specs" | "export";

const TABS: { id: TabId; label: string; icon: typeof Calculator }[] = [
  { id: "estimation", label: "Estimation", icon: Calculator },
  { id: "validation", label: "Validation", icon: ShieldCheck },
  { id: "diagrams", label: "Diagrams", icon: LayoutDashboard },
  { id: "specs", label: "Specs", icon: FileText },
  { id: "export", label: "Export", icon: Download },
];

function formatINR(n: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n);
}

export default function EstimationTerminalShell({
  isOpen,
  onToggle,
}: EstimationTerminalShellProps) {
  const { activeGraph, estimate: backendEstimate } = useDesignStore();
  const [activeTab, setActiveTab] = useState<TabId>("estimation");

  const estimate = useMemo(() => {
    if (!activeGraph) return null;
    const objectCount = activeGraph.objects.length;

    if (backendEstimate) {
      const area = backendEstimate.area?.total_sqft ?? (activeGraph.room.dimensions.length * activeGraph.room.dimensions.width);
      const sections = backendEstimate.estimate ?? {};
      const materialsCost = sections.materials?.total_cost ?? 0;
      const furnitureCost = sections.furniture?.total_cost ?? 0;
      const laborCost = sections.labor?.total_cost ?? 0;
      const servicesCost = sections.services?.total_cost ?? 0;
      const miscCost = sections.misc?.total_cost ?? 0;
      const total = backendEstimate.pricing_adjustments?.final_total
        ?? (materialsCost + furnitureCost + laborCost + servicesCost + miscCost);
      const costPerSqft = backendEstimate.area?.cost_per_sqft ?? (area > 0 ? total / area : 0);
      return {
        area,
        costPerSqft,
        materialsCost,
        furnitureCost,
        laborCost,
        servicesCost,
        miscCost,
        total,
        objectCount,
        source: "backend" as const,
        city: backendEstimate.region?.city,
        confidence: backendEstimate.confidence,
        breakdown: backendEstimate.breakdown,
        scenarios: backendEstimate.scenarios,
        currency: backendEstimate.currency ?? "INR",
      };
    }

    // Fallback (mock path): derive from the active graph rather than hardcoding.
    const area = activeGraph.room.dimensions.length * activeGraph.room.dimensions.width;
    const themeTier = (activeGraph.style?.primary ?? "modern").toLowerCase();
    const tierMultiplier =
      themeTier === "luxury" ? 1.6 :
      themeTier === "traditional" || themeTier === "contemporary" ? 1.2 :
      themeTier === "rustic" || themeTier === "industrial" ? 0.9 :
      themeTier === "minimalist" || themeTier === "scandinavian" ? 0.95 :
      1.0;
    const perObjectAvg = activeGraph.objects.reduce((sum, o) => {
      const d = o.dimensions;
      const vol = (d?.length ?? 1) * (d?.width ?? 1) * (d?.height ?? 1);
      return sum + Math.max(8000, Math.min(60000, 8000 + vol * 2400));
    }, 0);
    const materialsCost = Math.round(area * 620 * tierMultiplier);
    const furnitureCost = Math.round(perObjectAvg * tierMultiplier);
    const laborCost = Math.round(area * 460 * tierMultiplier);
    const total = materialsCost + furnitureCost + laborCost;
    return {
      area,
      costPerSqft: area > 0 ? Math.round(total / area) : 0,
      materialsCost,
      furnitureCost,
      laborCost,
      servicesCost: 0,
      miscCost: 0,
      total,
      objectCount,
      source: "local" as const,
      currency: "INR",
    };
  }, [activeGraph, backendEstimate]);

  return (
    <div className="border-t border-gray-200 flex-shrink-0">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-2 bg-gray-900 text-gray-300 hover:bg-gray-800 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Terminal size={14} />
          <span className="text-xs font-medium">Estimation Terminal</span>
          {estimate && (
            <span className="text-[10px] text-green-400 ml-2">
              Est. {formatINR(estimate.total)}
            </span>
          )}
        </div>
        {isOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      </button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: activeTab === "estimation" ? 220 : 420 }}
            exit={{ height: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="overflow-hidden"
            style={{ backgroundColor: activeTab === "estimation" ? "#0a0a0a" : "var(--paper)" }}
          >
            <div
              className="flex"
              style={{
                borderBottom: activeTab === "estimation" ? "1px solid #1f1f1f" : "1px solid var(--rule)",
                backgroundColor: activeTab === "estimation" ? "#0a0a0a" : "var(--paper-deep, #ece5d8)",
              }}
            >
              {TABS.map((tab) => {
                const Icon = tab.icon;
                const isActive = tab.id === activeTab;
                const onDark = activeTab === "estimation";
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors"
                    style={{
                      color: isActive
                        ? (onDark ? "#e5e5e5" : "var(--ink)")
                        : (onDark ? "#6b6b6b" : "var(--ink-3)"),
                      borderBottom: isActive
                        ? (onDark ? "1px solid #9ca3af" : "1px solid var(--ink)")
                        : "1px solid transparent",
                      fontWeight: isActive ? 600 : 500,
                    }}
                  >
                    <Icon size={12} />
                    {tab.label}
                  </button>
                );
              })}
            </div>

            {activeTab !== "estimation" && (
              <div style={{ height: "calc(100% - 37px)" }}>
                {activeTab === "validation" && <ValidationPanel />}
                {activeTab === "diagrams" && <DiagramsPanel />}
                {activeTab === "specs" && <SpecsPanel />}
                {activeTab === "export" && <ExportPanel />}
              </div>
            )}

            {activeTab === "estimation" && (
            <div className="p-4 font-mono text-xs text-gray-500 leading-relaxed overflow-y-auto" style={{ maxHeight: 170 }}>
              {!estimate ? (
                <>
                  <p className="text-gray-400">
                    <span className="text-green-400">$</span> estimation terminal ready
                  </p>
                  <p className="mt-1 text-gray-600">
                    Generate a design to begin cost estimation.
                  </p>
                </>
              ) : (
                <>
                  <p className="text-green-400">
                    $ estimate --format summary{" "}
                    <span className="text-gray-500">
                      ({estimate.source === "backend" ? "live backend" : "local fallback"}
                      {estimate.source === "backend" && estimate.city ? ` · ${estimate.city}` : ""})
                    </span>
                  </p>
                  <p className="mt-1 text-gray-300">
                    Room: {activeGraph!.room.type.replace(/_/g, " ")} | Area: {estimate.area} sqft | Objects: {estimate.objectCount}
                  </p>
                  <p className="mt-2 text-gray-400">--- Cost Breakdown ---</p>
                  <p className="text-gray-300">  Materials:  {formatINR(estimate.materialsCost)}</p>
                  <p className="text-gray-300">  Furniture:  {formatINR(estimate.furnitureCost)}</p>
                  <p className="text-gray-300">  Labor:      {formatINR(estimate.laborCost)}</p>
                  {estimate.servicesCost > 0 && (
                    <p className="text-gray-300">  Services:   {formatINR(estimate.servicesCost)}</p>
                  )}
                  {estimate.miscCost > 0 && (
                    <p className="text-gray-300">  Misc:       {formatINR(estimate.miscCost)}</p>
                  )}
                  <p className="mt-1 text-green-400 font-semibold">  TOTAL:      {formatINR(estimate.total)}</p>
                  <p className="mt-1 text-gray-500">  Cost/sqft:  {formatINR(Math.round(estimate.costPerSqft))}</p>
                  {estimate.source === "backend" && estimate.confidence && (
                    <p className="mt-1 text-gray-500">
                      Confidence: {estimate.confidence.level} ({Math.round((estimate.confidence.score ?? 0) * 100)}%)
                    </p>
                  )}
                  {estimate.source === "backend" && estimate.scenarios && estimate.scenarios.length > 0 && (
                    <>
                      <p className="mt-2 text-gray-400">--- Scenarios ---</p>
                      {estimate.scenarios.slice(0, 3).map((sc) => (
                        <p key={sc.name} className="text-gray-300">
                          {"  "}
                          {sc.name}: {formatINR(sc.total)}
                        </p>
                      ))}
                    </>
                  )}
                  <p className="mt-2 text-gray-600">Drag objects or change materials to see updated estimates.</p>
                </>
              )}
              <p className="mt-2 text-gray-700">
                <span className="text-gray-500">{">"}</span>{" "}
                <span className="animate-pulse">_</span>
              </p>
            </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
