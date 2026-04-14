"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import {
  PanelRightOpen,
  PanelLeftOpen,
  PanelLeftClose,
  Sparkles,
  RefreshCw,
  Send,
} from "lucide-react";
import { useImageGenStore, useChatStore } from "@/lib/store";
import type { GeneratedImage, ImageGeneration } from "@/lib/types";
import OutputCanvas from "../image/output-canvas";
import RightControlSidebar from "../controls/right-control-sidebar";
import EstimationTerminalShell from "../terminal/estimation-terminal-shell";

export default function ImageWorkspaceShell() {
  const {
    prompt,
    theme,
    drawingType,
    ratio,
    quality,
    rightSidebarOpen,
    terminalOpen,
    isGenerating,
    setPrompt,
    setRightSidebarOpen,
    toggleTerminal,
    setIsGenerating,
    addGeneration,
  } = useImageGenStore();
  const { sidebarOpen, toggleSidebar } = useChatStore();

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, []);

  useEffect(() => { resize(); }, [prompt, resize]);

  const handleGenerate = useCallback(() => {
    if (!prompt.trim() || isGenerating) return;

    setIsGenerating(true);

    const images: GeneratedImage[] = Array.from({ length: 4 }, () => ({
      id: crypto.randomUUID(),
      prompt,
      theme,
      drawingType,
      ratio,
      quality,
      status: "completed" as const,
      createdAt: new Date().toISOString(),
    }));

    const generation: ImageGeneration = {
      id: crypto.randomUUID(),
      prompt,
      negativePrompt: "",
      theme,
      drawingType,
      ratio,
      quality,
      images,
      createdAt: new Date().toISOString(),
    };

    setTimeout(() => {
      addGeneration(generation);
      setIsGenerating(false);
    }, 2000);
  }, [prompt, theme, drawingType, ratio, quality, isGenerating, setIsGenerating, addGeneration]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  };

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Header */}
      <header className="h-14 flex items-center justify-between px-4 border-b border-gray-100 bg-white flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={toggleSidebar}
            className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
          >
            {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>
          <span className="text-sm font-semibold tracking-wide text-gray-800">
            KATHA<span className="text-gray-400">.AI</span>
          </span>
          <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full font-medium">
            Image Studio
          </span>
        </div>
        {!rightSidebarOpen && (
          <button
            onClick={() => setRightSidebarOpen(true)}
            className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <PanelRightOpen size={18} />
          </button>
        )}
      </header>

      {/* Main content */}
      <div className="flex-1 flex min-h-0">
        {/* Center: Prompt + Canvas */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Prompt input bar */}
          <div className="border-b border-gray-100 bg-white px-4 py-3">
            <div className="mx-auto max-w-4xl">
              <div className="relative flex items-end gap-2">
                <textarea
                  ref={textareaRef}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Describe the architecture visual you want to generate..."
                  rows={1}
                  className="flex-1 resize-none rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 pr-12 text-[0.938rem] text-gray-900 placeholder:text-gray-400 focus:border-gray-300 focus:bg-white focus:outline-none focus:ring-1 focus:ring-gray-200 transition-colors"
                />
                <button
                  onClick={handleGenerate}
                  disabled={!prompt.trim() || isGenerating}
                  className="flex-shrink-0 flex items-center gap-2 px-5 py-3 bg-slate-900 text-white rounded-2xl text-sm font-medium hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {isGenerating ? (
                    <RefreshCw size={16} className="animate-spin" />
                  ) : (
                    <Sparkles size={16} />
                  )}
                  {isGenerating ? "Generating" : "Generate"}
                </button>
              </div>
            </div>
          </div>

          {/* Output canvas */}
          <OutputCanvas />

          {/* Bottom terminal */}
          <EstimationTerminalShell isOpen={terminalOpen} onToggle={toggleTerminal} />
        </div>

        {/* Right sidebar */}
        <RightControlSidebar
          isOpen={rightSidebarOpen}
          onClose={() => setRightSidebarOpen(false)}
        />
      </div>
    </div>
  );
}
