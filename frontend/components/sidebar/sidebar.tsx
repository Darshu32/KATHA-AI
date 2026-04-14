"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Plus,
  Search,
  MessageSquare,
  User,
  MessageCircle,
  ImageIcon,
  Calculator,
  FolderOpen,
  LayoutTemplate,
  ChevronDown,
  Wand2,
} from "lucide-react";
import { useChatStore, useAuthStore, useWorkspaceStore, useImageGenStore } from "@/lib/store";
import type { WorkspaceId, ArchTheme, DrawingType, ImageRatio, ImageQuality } from "@/lib/types";
import SidebarChatItem from "./sidebar-chat-item";

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
}

const WORKSPACES: { id: WorkspaceId; label: string; icon: typeof MessageCircle; enabled: boolean }[] = [
  { id: "knowledge-chat", label: "Knowledge Chat", icon: MessageCircle, enabled: true },
  { id: "image-generator", label: "Image Studio", icon: ImageIcon, enabled: true },
];

const FUTURE_NAV = [
  { label: "Estimation", icon: Calculator },
  { label: "Projects", icon: FolderOpen },
  { label: "Templates", icon: LayoutTemplate },
];

// ── Dropdown used in sidebar ───────────────────────────────────────────────

function SidebarDropdown<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const selected = options.find((o) => o.value === value);

  return (
    <div className="relative">
      <label className="block text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-1">
        {label}
      </label>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-2.5 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-800 hover:border-gray-300 transition-colors"
      >
        <span className="truncate">{selected?.label}</span>
        <ChevronDown size={12} className={`text-gray-400 transition-transform flex-shrink-0 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute z-40 top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-52 overflow-y-auto chat-scrollbar">
            {options.map((opt) => (
              <button
                key={opt.value}
                onClick={() => { onChange(opt.value); setOpen(false); }}
                className={`w-full text-left px-2.5 py-1.5 text-sm hover:bg-gray-50 transition-colors first:rounded-t-lg last:rounded-b-lg ${
                  opt.value === value ? "text-gray-900 font-medium bg-gray-50" : "text-gray-600"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Data ────────────────────────────────────────────────────────────────────

const THEMES: { value: ArchTheme; label: string }[] = [
  { value: "modern", label: "Modern" },
  { value: "contemporary", label: "Contemporary" },
  { value: "minimalist", label: "Minimalist" },
  { value: "traditional", label: "Traditional" },
  { value: "rustic", label: "Rustic" },
  { value: "industrial", label: "Industrial" },
  { value: "scandinavian", label: "Scandinavian" },
  { value: "bohemian", label: "Bohemian" },
  { value: "luxury", label: "Luxury" },
  { value: "coastal", label: "Coastal" },
];

const DRAWING_TYPES: { value: DrawingType; label: string }[] = [
  { value: "3d-render", label: "3D Render" },
  { value: "floor-plan", label: "Floor Plan" },
  { value: "elevation", label: "Elevation Drawing" },
  { value: "section", label: "Section Drawing" },
  { value: "structural", label: "Structural Diagram" },
  { value: "electrical", label: "Electrical Layout" },
  { value: "plumbing", label: "Plumbing Diagram" },
  { value: "interior-layout", label: "Interior Layout Plan" },
  { value: "concept-moodboard", label: "Concept / Mood Board" },
  { value: "working-drawings", label: "Working Drawings" },
  { value: "structural-drawings", label: "Structural Drawings" },
  { value: "door-window-details", label: "Door & Window Details" },
  { value: "staircase-details", label: "Staircase Details" },
  { value: "furniture-interior", label: "Furniture & Interior Details" },
  { value: "finishing-drawings", label: "Finishing Drawings" },
  { value: "mep-drawings", label: "MEP Drawings" },
  { value: "hvac-drawings", label: "HVAC Drawings" },
];

const RATIOS: { value: ImageRatio; label: string }[] = [
  { value: "1:1", label: "1:1" },
  { value: "16:9", label: "16:9" },
  { value: "4:3", label: "4:3" },
  { value: "3:4", label: "3:4" },
  { value: "9:16", label: "9:16" },
];

const QUALITIES: { value: ImageQuality; label: string }[] = [
  { value: "draft", label: "Draft" },
  { value: "standard", label: "Standard" },
  { value: "high", label: "High" },
  { value: "ultra", label: "Ultra" },
];

// ── Date grouping ──────────────────────────────────────────────────────────

function groupByDate(conversations: { updatedAt: string; id: string }[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<string, string[]> = {
    Today: [],
    Yesterday: [],
    "Previous 7 days": [],
    Older: [],
  };

  for (const c of conversations) {
    const d = new Date(c.updatedAt);
    if (d >= today) groups["Today"].push(c.id);
    else if (d >= yesterday) groups["Yesterday"].push(c.id);
    else if (d >= weekAgo) groups["Previous 7 days"].push(c.id);
    else groups["Older"].push(c.id);
  }

  return groups;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function Sidebar({ isOpen }: SidebarProps) {
  const [search, setSearch] = useState("");
  const {
    conversations,
    activeConversationId,
    createConversation,
    deleteConversation,
    setActiveConversation,
  } = useChatStore();
  const user = useAuthStore((s) => s.user);
  const { activeWorkspace, setActiveWorkspace } = useWorkspaceStore();
  const {
    theme, drawingType, ratio, quality, styleEnhance,
    setTheme, setDrawingType, setRatio, setQuality, setStyleEnhance,
  } = useImageGenStore();

  const sorted = useMemo(
    () => [...conversations].sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()),
    [conversations],
  );

  const filtered = useMemo(
    () => search ? sorted.filter((c) => c.title.toLowerCase().includes(search.toLowerCase())) : sorted,
    [sorted, search],
  );

  const groups = useMemo(() => groupByDate(filtered), [filtered]);

  return (
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.aside
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 288, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="h-screen bg-gray-50/80 border-r border-gray-200 flex flex-col overflow-hidden flex-shrink-0"
        >
          {/* Workspace switcher */}
          <div className="px-3 pt-3 pb-1 flex-shrink-0">
            <div className="flex items-center gap-1 p-1 bg-gray-100 rounded-xl">
              {WORKSPACES.map((ws) => {
                const Icon = ws.icon;
                const active = activeWorkspace === ws.id;
                return (
                  <button
                    key={ws.id}
                    onClick={() => ws.enabled && setActiveWorkspace(ws.id)}
                    className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-2 rounded-lg text-xs font-medium transition-all ${
                      active ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    <Icon size={14} />
                    <span className="truncate">{ws.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ─── Knowledge Chat sidebar content ─────────────────────────── */}
          {activeWorkspace === "knowledge-chat" && (
            <>
              <div className="px-3 pt-2 pb-1 flex-shrink-0">
                <button
                  onClick={() => createConversation()}
                  className="w-full flex items-center gap-2 px-3 py-2.5 border border-gray-200 rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors"
                >
                  <Plus size={16} />
                  New chat
                </button>
                <div className="relative mt-2">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search chats..."
                    className="w-full bg-white border border-gray-200 rounded-lg pl-8 pr-3 py-2 text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none focus:border-gray-300 transition-colors"
                  />
                </div>
              </div>

              <div className="flex-1 overflow-y-auto chat-scrollbar px-2 pb-2">
                {filtered.length === 0 ? (
                  <div className="text-center py-12 px-4">
                    <MessageSquare size={20} className="text-gray-300 mx-auto mb-2" />
                    <p className="text-xs text-gray-400">
                      {search ? "No matching conversations" : "No conversations yet"}
                    </p>
                  </div>
                ) : (
                  Object.entries(groups).map(
                    ([label, ids]) =>
                      ids.length > 0 && (
                        <div key={label} className="mt-3 first:mt-0">
                          <p className="text-xs font-medium text-gray-400 uppercase tracking-wider px-3 py-1.5">
                            {label}
                          </p>
                          <div className="space-y-0.5">
                            {ids.map((id) => {
                              const conv = filtered.find((c) => c.id === id)!;
                              return (
                                <SidebarChatItem
                                  key={id}
                                  conversation={conv}
                                  isActive={id === activeConversationId}
                                  onSelect={() => setActiveConversation(id)}
                                  onDelete={() => deleteConversation(id)}
                                />
                              );
                            })}
                          </div>
                        </div>
                      ),
                  )
                )}
              </div>
            </>
          )}

          {/* ─── Image Studio sidebar content ──────────────────────────── */}
          {activeWorkspace === "image-generator" && (
            <div className="flex-1 overflow-y-auto chat-scrollbar px-3 py-3 space-y-3">
              <SidebarDropdown value={theme} options={THEMES} onChange={setTheme} label="Architecture Theme" />
              <SidebarDropdown value={drawingType} options={DRAWING_TYPES} onChange={setDrawingType} label="Drawing Type" />

              <div className="grid grid-cols-2 gap-2">
                <SidebarDropdown value={ratio} options={RATIOS} onChange={setRatio} label="Ratio" />
                <SidebarDropdown value={quality} options={QUALITIES} onChange={setQuality} label="Quality" />
              </div>

              <div>
                <label className="block text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-1">
                  Style Enhance
                </label>
                <button
                  onClick={() => setStyleEnhance(!styleEnhance)}
                  className={`w-full flex items-center justify-center gap-1.5 px-2.5 py-2 rounded-lg border text-sm font-medium transition-all ${
                    styleEnhance
                      ? "bg-slate-900 border-slate-900 text-white"
                      : "bg-white border-gray-200 text-gray-600 hover:border-gray-300"
                  }`}
                >
                  <Wand2 size={14} />
                  {styleEnhance ? "On" : "Off"}
                </button>
              </div>

              {/* Separator */}
              <div className="border-t border-gray-200 pt-3">
                <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-2">
                  Recent Generations
                </p>
                <div className="text-center py-6">
                  <ImageIcon size={18} className="text-gray-300 mx-auto mb-1.5" />
                  <p className="text-xs text-gray-400">No generations yet</p>
                </div>
              </div>
            </div>
          )}

          {/* Future nav items */}
          <div className="px-3 py-2 border-t border-gray-200 flex-shrink-0">
            {FUTURE_NAV.map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.label}
                  className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-gray-400 cursor-not-allowed"
                >
                  <Icon size={15} />
                  <span>{item.label}</span>
                  <span className="ml-auto text-[10px] bg-gray-100 text-gray-400 px-1.5 py-0.5 rounded">
                    Soon
                  </span>
                </div>
              );
            })}
          </div>

          {/* User section */}
          <div className="p-3 border-t border-gray-200 flex-shrink-0">
            <div className="flex items-center gap-3 px-2">
              <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0">
                <User size={14} className="text-gray-500" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-700 truncate">
                  {user?.displayName || "Architect"}
                </p>
                <p className="text-xs text-gray-400 truncate">
                  {user?.email || "Architecture Intelligence"}
                </p>
              </div>
            </div>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
