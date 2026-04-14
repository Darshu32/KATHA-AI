"use client";

import { useImageGenStore } from "@/lib/store";

export default function ModeSwitcher2D3D() {
  const { viewMode, setViewMode } = useImageGenStore();

  return (
    <div className="flex items-center gap-1 p-1 bg-gray-100 rounded-xl">
      <button
        onClick={() => setViewMode("2d")}
        className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-all ${
          viewMode === "2d"
            ? "bg-white text-gray-900 shadow-sm"
            : "text-gray-500 hover:text-gray-700"
        }`}
      >
        2D View
      </button>
      <button
        onClick={() => setViewMode("3d")}
        className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-all ${
          viewMode === "3d"
            ? "bg-white text-gray-900 shadow-sm"
            : "text-gray-500 hover:text-gray-700"
        }`}
      >
        3D View
      </button>
    </div>
  );
}
