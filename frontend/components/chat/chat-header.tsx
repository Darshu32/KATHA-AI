"use client";

import { useState, useRef, useEffect } from "react";
import {
  PanelLeftOpen,
  PanelLeftClose,
  RotateCcw,
  NotebookPen,
  ChevronDown,
  Zap,
  BookOpen,
  Gauge,
} from "lucide-react";
import { useChatStore, useNotesStore } from "@/lib/store";
import type { ChatMode } from "@/lib/types";

interface ChatHeaderProps {
  conversationTitle?: string;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  onClearChat?: () => void;
}

const MODES: { value: ChatMode; label: string; icon: typeof Zap; hint: string }[] = [
  { value: "auto", label: "Auto", icon: Gauge, hint: "Balanced depth" },
  { value: "quick", label: "Quick", icon: Zap, hint: "Short answers" },
  { value: "deep", label: "Deep", icon: BookOpen, hint: "Research mode" },
];

export default function ChatHeader({
  conversationTitle,
  sidebarOpen,
  onToggleSidebar,
  onClearChat,
}: ChatHeaderProps) {
  const chatMode = useChatStore((s) => s.chatMode);
  const setChatMode = useChatStore((s) => s.setChatMode);
  const { notesPanelOpen, toggleNotesPanel, notebook } = useNotesStore();
  const [modeOpen, setModeOpen] = useState(false);
  const modeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (modeRef.current && !modeRef.current.contains(e.target as Node)) setModeOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const activeMode = MODES.find((m) => m.value === chatMode) ?? MODES[0];
  const ActiveIcon = activeMode.icon;

  return (
    <header
      className="h-12 flex items-center justify-between px-3"
      style={{
        backgroundColor: "var(--paper)",
        borderBottom: "1px solid var(--rule)",
        fontFamily: "var(--sans)",
        flexShrink: 0,
      }}
    >
      {/* Left */}
      <div className="flex items-center gap-2 min-w-0">
        <button
          onClick={onToggleSidebar}
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
        {conversationTitle && conversationTitle !== "New conversation" && (
          <>
            <span
              className="mx-1"
              style={{ fontSize: 11, color: "var(--ink-3)", fontFamily: "var(--mono)", letterSpacing: "0.1em" }}
            >
              /
            </span>
            <span
              className="truncate max-w-[320px]"
              style={{ fontSize: 13, color: "var(--ink-2)", fontWeight: 500, letterSpacing: "-0.005em" }}
            >
              {conversationTitle}
            </span>
          </>
        )}
      </div>

      {/* Right — just mode + notes + clear, compact */}
      <div className="flex items-center gap-1">
        {/* Mode selector */}
        <div ref={modeRef} className="relative">
          <button
            onClick={() => setModeOpen((v) => !v)}
            className="inline-flex items-center gap-1.5 pl-2 pr-1.5 h-8 rounded-md transition-colors"
            style={{
              fontSize: 12,
              color: "var(--ink-2)",
              fontWeight: 500,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--paper-2)")}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
          >
            <ActiveIcon size={13} style={{ color: "var(--accent)" }} />
            {activeMode.label}
            <ChevronDown size={11} className={`opacity-60 transition-transform ${modeOpen ? "rotate-180" : ""}`} />
          </button>

          {modeOpen && (
            <div
              className="absolute right-0 top-full mt-1.5 w-[180px] rounded-xl overflow-hidden z-50"
              style={{
                backgroundColor: "#fff",
                border: "1px solid var(--rule)",
                boxShadow: "0 10px 30px -12px rgba(17,17,16,0.25)",
              }}
            >
              {MODES.map((m) => {
                const I = m.icon;
                const active = m.value === chatMode;
                return (
                  <button
                    key={m.value}
                    onClick={() => {
                      setChatMode(m.value);
                      setModeOpen(false);
                    }}
                    className="w-full flex items-start gap-2.5 px-3 py-2 transition-colors text-left"
                    style={{
                      backgroundColor: active ? "var(--paper-2)" : "transparent",
                    }}
                    onMouseEnter={(e) => {
                      if (!active) e.currentTarget.style.backgroundColor = "var(--paper-2)";
                    }}
                    onMouseLeave={(e) => {
                      if (!active) e.currentTarget.style.backgroundColor = "transparent";
                    }}
                  >
                    <I size={13} className="mt-0.5" style={{ color: active ? "var(--accent)" : "var(--ink-3)" }} />
                    <div className="flex-1">
                      <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink)", letterSpacing: "-0.005em" }}>
                        {m.label}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 1 }}>{m.hint}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="h-5 w-px mx-1" style={{ backgroundColor: "var(--rule)" }} />

        <button
          onClick={toggleNotesPanel}
          className="relative p-1.5 rounded-md transition-colors"
          style={{
            color: notesPanelOpen ? "var(--ink)" : "var(--ink-3)",
            backgroundColor: notesPanelOpen ? "var(--paper-2)" : "transparent",
          }}
          title="Notes"
        >
          <NotebookPen size={15} />
          {notebook.sections.length > 0 && (
            <span
              className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: "var(--accent)" }}
            />
          )}
        </button>

        <button
          onClick={onClearChat}
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
          title="Clear chat"
        >
          <RotateCcw size={15} />
        </button>
      </div>
    </header>
  );
}
