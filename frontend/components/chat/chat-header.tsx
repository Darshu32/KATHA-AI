"use client";

import { PanelLeftOpen, PanelLeftClose, RotateCcw, Download, Pin, Zap, BookOpen } from "lucide-react";
import { useChatStore } from "@/lib/store";
import type { ChatMode } from "@/lib/types";

interface ChatHeaderProps {
  conversationTitle?: string;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  onClearChat?: () => void;
}

export default function ChatHeader({
  conversationTitle,
  sidebarOpen,
  onToggleSidebar,
  onClearChat,
}: ChatHeaderProps) {
  const chatMode = useChatStore((s) => s.chatMode);
  const setChatMode = useChatStore((s) => s.setChatMode);

  const modeOptions: { value: ChatMode; label: string; icon: typeof Zap }[] = [
    { value: "auto", label: "Auto", icon: Zap },
    { value: "quick", label: "Quick", icon: Zap },
    { value: "deep", label: "Deep", icon: BookOpen },
  ];

  return (
    <header className="h-14 flex items-center justify-between px-4 border-b border-gray-100 bg-white flex-shrink-0">
      {/* Left */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
        >
          {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
        </button>
        {conversationTitle && conversationTitle !== "New conversation" && (
          <span className="text-sm font-medium text-gray-600 truncate max-w-[200px]">
            {conversationTitle}
          </span>
        )}
      </div>

      {/* Center */}
      <div className="absolute left-1/2 -translate-x-1/2 flex items-center gap-3">
        <span className="text-sm font-semibold tracking-wide text-gray-800">
          KATHA
          <span className="text-gray-400">.AI</span>
        </span>

        {/* Mode Toggle */}
        <div className="flex items-center bg-gray-100 rounded-full p-0.5">
          {modeOptions.map((opt) => {
            const Icon = opt.icon;
            const isActive = chatMode === opt.value;
            return (
              <button
                key={opt.value}
                onClick={() => setChatMode(opt.value)}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium transition-all ${
                  isActive
                    ? "bg-white text-gray-800 shadow-sm"
                    : "text-gray-500 hover:text-gray-700"
                }`}
                title={`${opt.label} mode`}
              >
                <Icon size={12} />
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Right */}
      <div className="flex items-center gap-1">
        <button
          onClick={onClearChat}
          className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
          title="Clear chat"
        >
          <RotateCcw size={16} />
        </button>
        <button
          className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
          title="Export"
        >
          <Download size={16} />
        </button>
        <button
          className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
          title="Pin"
        >
          <Pin size={16} />
        </button>
      </div>
    </header>
  );
}
