"use client";

import { motion } from "framer-motion";
import {
  ImageIcon,
  Maximize2,
  RefreshCw,
  Download,
  FolderPlus,
  ArrowRight,
} from "lucide-react";
import { useImageGenStore } from "@/lib/store";

function PlaceholderCard({ index }: { index: number }) {
  const colors = [
    "from-gray-100 to-gray-50",
    "from-gray-50 to-gray-100",
    "from-gray-100 to-white",
    "from-white to-gray-100",
  ];

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: index * 0.1 }}
      className={`relative aspect-video bg-gradient-to-br ${colors[index % 4]} rounded-2xl border border-gray-200 overflow-hidden group cursor-pointer hover:border-gray-300 transition-all`}
    >
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="text-center">
          <ImageIcon size={32} className="text-gray-300 mx-auto mb-2" />
          <p className="text-xs text-gray-400">Variation {index + 1}</p>
        </div>
      </div>

      {/* Hover overlay */}
      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/5 transition-colors" />
      <div className="absolute bottom-0 left-0 right-0 p-3 flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
        <button className="p-1.5 bg-white/90 backdrop-blur rounded-lg text-gray-600 hover:text-gray-900 transition-colors shadow-sm">
          <Maximize2 size={13} />
        </button>
        <button className="p-1.5 bg-white/90 backdrop-blur rounded-lg text-gray-600 hover:text-gray-900 transition-colors shadow-sm">
          <RefreshCw size={13} />
        </button>
        <button className="p-1.5 bg-white/90 backdrop-blur rounded-lg text-gray-600 hover:text-gray-900 transition-colors shadow-sm">
          <Download size={13} />
        </button>
        <button className="p-1.5 bg-white/90 backdrop-blur rounded-lg text-gray-600 hover:text-gray-900 transition-colors shadow-sm">
          <FolderPlus size={13} />
        </button>
        <button className="ml-auto p-1.5 bg-white/90 backdrop-blur rounded-lg text-gray-600 hover:text-gray-900 transition-colors shadow-sm">
          <ArrowRight size={13} />
        </button>
      </div>
    </motion.div>
  );
}

export default function OutputCanvas() {
  const { generations, isGenerating } = useImageGenStore();

  return (
    <div className="flex-1 overflow-y-auto chat-scrollbar p-4">
      {generations.length === 0 && !isGenerating ? (
        /* Empty state */
        <div className="h-full flex items-center justify-center">
          <div className="text-center max-w-sm">
            <div className="w-16 h-16 rounded-2xl bg-gray-50 border border-gray-100 flex items-center justify-center mx-auto mb-4">
              <ImageIcon size={28} className="text-gray-300" />
            </div>
            <h3 className="text-lg font-semibold text-gray-800 mb-2">
              Architecture Visual Studio
            </h3>
            <p className="text-sm text-gray-500 leading-relaxed">
              Enter a prompt above to generate architectural visuals.
              Choose from floor plans, elevations, 3D renders, and more.
            </p>

            {/* Preview grid */}
            <div className="grid grid-cols-2 gap-3 mt-6">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="aspect-video bg-gradient-to-br from-gray-50 to-gray-100 rounded-xl border border-gray-200"
                />
              ))}
            </div>
          </div>
        </div>
      ) : (
        /* Generated images grid */
        <div>
          {isGenerating && (
            <div className="mb-6">
              <div className="flex items-center gap-2 mb-3">
                <RefreshCw size={14} className="text-gray-400 animate-spin" />
                <span className="text-sm text-gray-500">Generating variations...</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {[0, 1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="aspect-video bg-gradient-to-br from-gray-100 to-gray-50 rounded-2xl border border-gray-200 animate-pulse"
                  />
                ))}
              </div>
            </div>
          )}

          {generations.map((gen) => (
            <div key={gen.id} className="mb-6">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <p className="text-sm font-medium text-gray-800 truncate max-w-md">
                    {gen.prompt}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {gen.theme} &middot; {gen.drawingType.replace(/-/g, " ")} &middot;{" "}
                    {new Date(gen.createdAt).toLocaleTimeString()}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {gen.images.map((img, i) => (
                  <PlaceholderCard key={img.id} index={i} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
