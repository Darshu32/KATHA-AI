"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import {
  PanelRightOpen,
  PanelLeftOpen,
  PanelLeftClose,
  Sparkles,
  RefreshCw,
} from "lucide-react";
import { useImageGenStore, useChatStore, useDesignStore } from "@/lib/store";
import { design as designApi } from "@/lib/api-client";
import { MOCK_LIVING_ROOM, MOCK_2BHK, getMockGraphForPreset } from "@/lib/mock-design-graph";
import type { DesignGraph } from "@/lib/types";
import OutputCanvas from "../image/output-canvas";
import ImageEmptyHero from "../image/image-empty-hero";
import RightControlSidebar from "../controls/right-control-sidebar";
import EstimationTerminalShell from "../terminal/estimation-terminal-shell";

export default function ImageWorkspaceShell() {
  const {
    prompt,
    theme,
    drawingType,
    ratio,
    quality,
    camera,
    lighting,
    viewMode,
    rightSidebarOpen,
    terminalOpen,
    isGenerating,
    setPrompt,
    setRightSidebarOpen,
    toggleTerminal,
    setIsGenerating,
  } = useImageGenStore();
  const { sidebarOpen, toggleSidebar } = useChatStore();
  const { setActiveGraph, setLoading, activeGraph, setEstimate } = useDesignStore();

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, []);

  useEffect(() => { resize(); }, [prompt, resize]);

  const handleGenerate = useCallback(async () => {
    if (!prompt.trim() || isGenerating) return;

    setIsGenerating(true);
    setLoading(true);

    try {
      // Try backend first
      const result = await designApi.generate("", "demo", {
        prompt,
        room_type: drawingType === "floor-plan" ? "living_room" : "living_room",
        style: theme,
        camera,
        lighting,
        view_mode: viewMode,
        ratio,
        quality,
        drawing_type: drawingType,
      });
      if (result?.graph_data) {
        setActiveGraph(result.graph_data as unknown as DesignGraph);
        setEstimate((result as { estimate?: unknown }).estimate as never);
      } else {
        throw new Error("No graph data");
      }
    } catch {
      // Fallback to mock data
      const lowerPrompt = prompt.toLowerCase();
      if (lowerPrompt.includes("2bhk") || lowerPrompt.includes("2 bhk") || lowerPrompt.includes("2-bhk")) {
        setActiveGraph(MOCK_2BHK);
      } else {
        setActiveGraph(MOCK_LIVING_ROOM);
      }
      setEstimate(null);
    } finally {
      setIsGenerating(false);
      setLoading(false);
    }
  }, [prompt, theme, drawingType, ratio, quality, camera, lighting, viewMode, isGenerating, setIsGenerating, setActiveGraph, setEstimate, setLoading]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  };

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Header */}
      <header
        className="h-12 flex items-center justify-between px-3"
        style={{
          backgroundColor: "var(--paper)",
          borderBottom: "1px solid var(--rule)",
          fontFamily: "var(--sans)",
          flexShrink: 0,
        }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <button
            onClick={toggleSidebar}
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
            {sidebarOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
          </button>
          <span className="mx-1" style={{ fontSize: 11, color: "var(--ink-3)", fontFamily: "var(--mono)", letterSpacing: "0.1em" }}>
            /
          </span>
          <span style={{ fontSize: 13, color: "var(--ink-2)", fontWeight: 500, letterSpacing: "-0.005em" }}>
            Studio
          </span>
          {activeGraph && (
            <span
              className="ml-2"
              style={{ fontSize: 11, color: "var(--ink-3)", fontFamily: "var(--mono)", letterSpacing: "0.04em" }}
            >
              {activeGraph.room.type.replace(/_/g, " ")} · {activeGraph.room.dimensions.length}'×{activeGraph.room.dimensions.width}'
            </span>
          )}
        </div>
        {!rightSidebarOpen && (
          <button
            onClick={() => setRightSidebarOpen(true)}
            className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-md transition-colors"
            style={{ fontSize: 12, color: "var(--ink-2)", fontWeight: 500 }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--paper-2)")}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
          >
            <PanelRightOpen size={14} />
            Parameters
          </button>
        )}
      </header>

      {/* Main content */}
      <div className="flex-1 flex min-h-0">
        {/* Center: Prompt + Canvas */}
        <div className="flex-1 flex flex-col min-w-0">
          {!activeGraph && !isGenerating ? (
            <ImageEmptyHero onGenerate={handleGenerate} disabled={isGenerating} />
          ) : (
            <>
              {/* Prompt input bar */}
              <div className="px-4 py-3" style={{ backgroundColor: "var(--paper)", borderBottom: "1px solid var(--rule)" }}>
                <div className="mx-auto" style={{ maxWidth: 860 }}>
                  <div
                    className="relative flex items-center gap-2 rounded-[18px] bg-white px-4 py-2"
                    style={{
                      border: "1px solid var(--rule)",
                      boxShadow: "0 1px 2px rgba(17,17,16,0.04)",
                    }}
                  >
                    <textarea
                      ref={textareaRef}
                      value={prompt}
                      onChange={(e) => setPrompt(e.target.value)}
                      onKeyDown={handleKeyDown}
                      placeholder="Refine the design — add courtyard, change facade, adjust layout…"
                      rows={1}
                      className="flex-1 resize-none bg-transparent py-1.5 focus:outline-none"
                      style={{
                        fontFamily: "var(--sans)",
                        fontSize: 14.5,
                        lineHeight: 1.55,
                        color: "var(--ink)",
                        letterSpacing: "-0.005em",
                      }}
                    />
                    <button
                      onClick={handleGenerate}
                      disabled={!prompt.trim() || isGenerating}
                      className="flex-shrink-0 inline-flex items-center gap-1.5 h-9 px-3.5 rounded-full transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                      style={{
                        backgroundColor: "var(--ink)",
                        color: "var(--paper)",
                        fontFamily: "var(--sans)",
                        fontSize: 12.5,
                        fontWeight: 500,
                      }}
                    >
                      {isGenerating ? <RefreshCw size={13} className="animate-spin" /> : <Sparkles size={13} />}
                      {isGenerating ? "Drafting" : "Generate"}
                    </button>
                  </div>
                </div>
              </div>

              {/* Output canvas */}
              <OutputCanvas />

              {/* Bottom terminal */}
              <EstimationTerminalShell isOpen={terminalOpen} onToggle={toggleTerminal} />
            </>
          )}
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
