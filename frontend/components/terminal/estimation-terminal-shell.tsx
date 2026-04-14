"use client";

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

export default function EstimationTerminalShell({
  isOpen,
  onToggle,
}: EstimationTerminalShellProps) {
  return (
    <div className="border-t border-gray-200 flex-shrink-0">
      {/* Toggle bar */}
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-2 bg-gray-900 text-gray-300 hover:bg-gray-800 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Terminal size={14} />
          <span className="text-xs font-medium">Estimation Terminal</span>
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
            {/* Tabs */}
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

            {/* Terminal content */}
            <div className="p-4 font-mono text-xs text-gray-500 leading-relaxed">
              <p className="text-gray-400">
                <span className="text-green-400">$</span> estimation terminal
                ready
              </p>
              <p className="mt-1 text-gray-600">
                Generate a design to begin cost estimation, BOQ generation, and
                area calculations.
              </p>
              <p className="mt-3 text-gray-700">
                <span className="text-gray-500">{'>'}</span>{" "}
                <span className="animate-pulse">_</span>
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
