"use client";

import { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Terminal,
  ChevronUp,
  ChevronDown,
  Calculator,
  FileSpreadsheet,
  BarChart3,
  DollarSign,
} from "lucide-react";
import { useDesignStore } from "@/lib/store";

interface EstimationTerminalShellProps {
  isOpen: boolean;
  onToggle: () => void;
}

const TABS = [
  { id: "estimation", label: "Estimation", icon: Calculator },
  { id: "boq", label: "BOQ", icon: FileSpreadsheet },
  { id: "area", label: "Area Calc", icon: BarChart3 },
  { id: "costing", label: "Costing", icon: DollarSign },
];

function formatINR(n: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n);
}

export default function EstimationTerminalShell({
  isOpen,
  onToggle,
}: EstimationTerminalShellProps) {
  const { activeGraph } = useDesignStore();

  const estimate = useMemo(() => {
    if (!activeGraph) return null;
    const area = activeGraph.room.dimensions.length * activeGraph.room.dimensions.width;
    const costPerSqft = 1800;
    const materialsCost = area * 600;
    const furnitureCost = activeGraph.objects.length * 15000;
    const laborCost = area * 450;
    const total = materialsCost + furnitureCost + laborCost;
    return { area, costPerSqft, materialsCost, furnitureCost, laborCost, total, objectCount: activeGraph.objects.length };
  }, [activeGraph]);

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
            animate={{ height: 220 }}
            exit={{ height: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="bg-gray-950 overflow-hidden"
          >
            <div className="flex border-b border-gray-800">
              {TABS.map((tab, i) => {
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors ${
                      i === 0
                        ? "text-gray-200 border-b border-gray-400"
                        : "text-gray-500 hover:text-gray-400"
                    }`}
                  >
                    <Icon size={12} />
                    {tab.label}
                  </button>
                );
              })}
            </div>

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
                  <p className="text-green-400">$ estimate --format summary</p>
                  <p className="mt-1 text-gray-300">
                    Room: {activeGraph!.room.type.replace(/_/g, " ")} | Area: {estimate.area} sqft | Objects: {estimate.objectCount}
                  </p>
                  <p className="mt-2 text-gray-400">--- Cost Breakdown ---</p>
                  <p className="text-gray-300">  Materials:  {formatINR(estimate.materialsCost)}</p>
                  <p className="text-gray-300">  Furniture:  {formatINR(estimate.furnitureCost)}</p>
                  <p className="text-gray-300">  Labor:      {formatINR(estimate.laborCost)}</p>
                  <p className="mt-1 text-green-400 font-semibold">  TOTAL:      {formatINR(estimate.total)}</p>
                  <p className="mt-1 text-gray-500">  Cost/sqft:  {formatINR(Math.round(estimate.total / estimate.area))}</p>
                  <p className="mt-2 text-gray-600">Drag objects or change materials to see updated estimates.</p>
                </>
              )}
              <p className="mt-2 text-gray-700">
                <span className="text-gray-500">{">"}</span>{" "}
                <span className="animate-pulse">_</span>
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
