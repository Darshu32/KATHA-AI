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

// Currency-aware money formatter. Defaults to INR (home market) but
// renders €/AED/$/A$ for the project's region so non-Indian client demos
// never show rupees. Locale tracks the currency for correct grouping.
const LOCALE_BY_CURRENCY: Record<string, string> = {
  INR: "en-IN",
  EUR: "de-DE",
  AED: "en-AE",
  USD: "en-US",
  AUD: "en-AU",
  GBP: "en-GB",
};

function formatMoney(n: number, currency = "INR") {
  const code = (currency || "INR").toUpperCase();
  const locale = LOCALE_BY_CURRENCY[code] ?? "en-US";
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: code,
      maximumFractionDigits: 0,
    }).format(n);
  } catch {
    // Unknown ISO code — fall back to a plain number + code suffix.
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(n)} ${code}`;
  }
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
      // Region display block (preferred): carries the project's currency
      // + the converted total. Falls back to the INR base when absent.
      const display = backendEstimate.display;
      const baseTotal = backendEstimate.pricing_adjustments?.final_total ?? 0;
      // Sub-sections are authored in INR base; convert them by the same
      // ratio the pipeline used for the headline total so the breakdown
      // stays internally consistent with the (converted) TOTAL line.
      const fxRatio = display && baseTotal > 0 ? display.final_total / baseTotal : 1;
      const materialsCost = (sections.materials?.total_cost ?? 0) * fxRatio;
      const furnitureCost = (sections.furniture?.total_cost ?? 0) * fxRatio;
      const laborCost = (sections.labor?.total_cost ?? 0) * fxRatio;
      const servicesCost = (sections.services?.total_cost ?? 0) * fxRatio;
      const miscCost = (sections.misc?.total_cost ?? 0) * fxRatio;
      const total = display?.final_total
        ?? baseTotal
        ?? (materialsCost + furnitureCost + laborCost + servicesCost + miscCost);
      const costPerSqft = display?.cost_per_sqft
        ?? backendEstimate.area?.cost_per_sqft
        ?? (area > 0 ? total / area : 0);
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
        currency: display?.currency ?? backendEstimate.currency ?? "INR",
        fxRatio,
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
      fxRatio: 1,
    };
  }, [activeGraph, backendEstimate]);

  return (
    <div className="border-t border-hairline flex-shrink-0">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-2 bg-paper-deep text-ink-soft hover:bg-paper-edge transition-colors"
      >
        <div className="flex items-center gap-2">
          <Terminal size={14} />
          <span className="text-xs font-medium">Estimation Terminal</span>
          {estimate && (
            <span className="text-[10px] text-pencil ml-2">
              Est. {formatMoney(estimate.total, estimate.currency)}
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
            style={{ backgroundColor: "var(--paper-soft)" }}
          >
            <div
              className="flex"
              style={{
                borderBottom: "1px solid var(--hairline)",
                backgroundColor: "var(--paper-deep)",
              }}
            >
              {TABS.map((tab) => {
                const Icon = tab.icon;
                const isActive = tab.id === activeTab;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors"
                    style={{
                      color: isActive ? "var(--ink)" : "var(--ink-soft)",
                      borderBottom: isActive
                        ? "1px solid var(--ink)"
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
            <div className="p-4 font-mono text-xs text-ink-mute leading-relaxed overflow-y-auto" style={{ maxHeight: 170 }}>
              {!estimate ? (
                <>
                  <p className="text-ink-soft">
                    <span className="text-pencil">$</span> estimation terminal ready
                  </p>
                  <p className="mt-1 text-ink-mute">
                    Generate a design to begin cost estimation.
                  </p>
                </>
              ) : (
                <>
                  <p className="text-pencil">
                    $ estimate --format summary{" "}
                    <span className="text-ink-mute">
                      ({estimate.source === "backend" ? "live backend" : "local fallback"}
                      {estimate.source === "backend" && estimate.city ? ` · ${estimate.city}` : ""})
                    </span>
                  </p>
                  <p className="mt-1 text-ink">
                    Room: {activeGraph!.room.type.replace(/_/g, " ")} | Area: {estimate.area} sqft | Objects: {estimate.objectCount}
                  </p>
                  <p className="mt-2 text-ink-soft">--- Cost Breakdown ---</p>
                  <p className="text-ink">  Materials:  {formatMoney(estimate.materialsCost, estimate.currency)}</p>
                  <p className="text-ink">  Furniture:  {formatMoney(estimate.furnitureCost, estimate.currency)}</p>
                  <p className="text-ink">  Labor:      {formatMoney(estimate.laborCost, estimate.currency)}</p>
                  {estimate.servicesCost > 0 && (
                    <p className="text-ink">  Services:   {formatMoney(estimate.servicesCost, estimate.currency)}</p>
                  )}
                  {estimate.miscCost > 0 && (
                    <p className="text-ink">  Misc:       {formatMoney(estimate.miscCost, estimate.currency)}</p>
                  )}
                  <p className="mt-1 text-pencil font-semibold">  TOTAL:      {formatMoney(estimate.total, estimate.currency)}</p>
                  <p className="mt-1 text-ink-soft">  Cost/sqft:  {formatMoney(Math.round(estimate.costPerSqft), estimate.currency)}</p>
                  {estimate.source === "backend" && estimate.confidence && (
                    <p className="mt-1 text-ink-soft">
                      Confidence: {estimate.confidence.level} ({Math.round((estimate.confidence.score ?? 0) * 100)}%)
                    </p>
                  )}
                  {estimate.source === "backend" && estimate.scenarios && estimate.scenarios.length > 0 && (
                    <>
                      <p className="mt-2 text-ink-soft">--- Scenarios ---</p>
                      {estimate.scenarios.slice(0, 3).map((sc) => (
                        <p key={sc.name} className="text-ink">
                          {"  "}
                          {sc.name}: {formatMoney(sc.total * estimate.fxRatio, estimate.currency)}
                        </p>
                      ))}
                    </>
                  )}
                  <p className="mt-2 text-ink-mute">Drag objects or change materials to see updated estimates.</p>
                </>
              )}
              <p className="mt-2 text-ink-mute">
                <span className="text-ink-soft">{">"}</span>{" "}
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
