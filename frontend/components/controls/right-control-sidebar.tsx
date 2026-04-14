"use client";

import { motion, AnimatePresence } from "framer-motion";
import {
  Layers,
  Camera,
  Palette,
  Sun,
  Download,
  History,
  Lightbulb,
  PanelRightClose,
} from "lucide-react";
import { useImageGenStore } from "@/lib/store";
import ModeSwitcher2D3D from "./mode-switcher-2d3d";

interface RightControlSidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

function ControlSection({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: typeof Layers;
  children: React.ReactNode;
}) {
  return (
    <div className="px-4 py-3 border-b border-gray-100">
      <div className="flex items-center gap-2 mb-2.5">
        <Icon size={14} className="text-gray-400" />
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}

function PresetChip({ label, active }: { label: string; active?: boolean }) {
  return (
    <button
      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
        active
          ? "bg-slate-900 text-white"
          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
      }`}
    >
      {label}
    </button>
  );
}

export default function RightControlSidebar({
  isOpen,
  onClose,
}: RightControlSidebarProps) {
  return (
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.aside
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 280, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="h-full bg-white border-l border-gray-200 flex flex-col overflow-hidden flex-shrink-0"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 flex-shrink-0">
            <span className="text-sm font-semibold text-gray-800">Controls</span>
            <button
              onClick={onClose}
              className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <PanelRightClose size={16} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto chat-scrollbar">
            {/* 2D / 3D Mode */}
            <ControlSection title="View Mode" icon={Layers}>
              <ModeSwitcher2D3D />
            </ControlSection>

            {/* Layers */}
            <ControlSection title="Layers" icon={Layers}>
              <div className="space-y-1.5">
                {["Base render", "Wireframe", "Materials", "Lighting"].map(
                  (layer) => (
                    <div
                      key={layer}
                      className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-gray-50 transition-colors"
                    >
                      <span className="text-sm text-gray-700">{layer}</span>
                      <div className="w-8 h-4 bg-gray-200 rounded-full relative cursor-pointer">
                        <div className="absolute left-0.5 top-0.5 w-3 h-3 bg-white rounded-full shadow-sm" />
                      </div>
                    </div>
                  ),
                )}
              </div>
            </ControlSection>

            {/* Camera presets */}
            <ControlSection title="Camera" icon={Camera}>
              <div className="flex flex-wrap gap-1.5">
                <PresetChip label="Front" active />
                <PresetChip label="Aerial" />
                <PresetChip label="Interior" />
                <PresetChip label="Detail" />
                <PresetChip label="Eye-level" />
              </div>
            </ControlSection>

            {/* Material presets */}
            <ControlSection title="Materials" icon={Palette}>
              <div className="grid grid-cols-4 gap-2">
                {[
                  { color: "bg-gray-200", label: "Concrete" },
                  { color: "bg-amber-100", label: "Wood" },
                  { color: "bg-gray-400", label: "Steel" },
                  { color: "bg-sky-100", label: "Glass" },
                  { color: "bg-stone-300", label: "Stone" },
                  { color: "bg-orange-200", label: "Brick" },
                  { color: "bg-emerald-100", label: "Marble" },
                  { color: "bg-zinc-200", label: "Metal" },
                ].map((mat) => (
                  <div key={mat.label} className="text-center cursor-pointer group">
                    <div
                      className={`w-full aspect-square ${mat.color} rounded-lg border border-gray-200 group-hover:border-gray-400 transition-colors`}
                    />
                    <p className="text-[10px] text-gray-500 mt-1">{mat.label}</p>
                  </div>
                ))}
              </div>
            </ControlSection>

            {/* Lighting */}
            <ControlSection title="Lighting" icon={Sun}>
              <div className="flex flex-wrap gap-1.5">
                <PresetChip label="Daylight" active />
                <PresetChip label="Golden hour" />
                <PresetChip label="Night" />
                <PresetChip label="Studio" />
                <PresetChip label="Overcast" />
              </div>
            </ControlSection>

            {/* Export */}
            <ControlSection title="Export" icon={Download}>
              <div className="space-y-1.5">
                {["PNG (High-res)", "JPEG", "SVG", "PDF"].map((format) => (
                  <button
                    key={format}
                    className="w-full text-left px-3 py-2 text-sm text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    {format}
                  </button>
                ))}
              </div>
            </ControlSection>

            {/* Version history */}
            <ControlSection title="History" icon={History}>
              <p className="text-xs text-gray-400">No versions yet</p>
            </ControlSection>

            {/* Prompt suggestions */}
            <ControlSection title="Suggestions" icon={Lightbulb}>
              <div className="space-y-1.5">
                {[
                  "Add more greenery",
                  "Change to warmer tones",
                  "Add pool in foreground",
                  "Switch to night view",
                ].map((sug) => (
                  <button
                    key={sug}
                    className="w-full text-left px-3 py-2 text-xs text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50 hover:text-gray-700 transition-colors"
                  >
                    {sug}
                  </button>
                ))}
              </div>
            </ControlSection>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
