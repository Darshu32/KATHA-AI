"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  Plus,
  Search,
  MessageSquare,
  MessageCircle,
  ImageIcon,
} from "lucide-react";
import { useChatStore, useAuthStore, useWorkspaceStore } from "@/lib/store";
import type { WorkspaceId } from "@/lib/types";
import SidebarChatItem from "./sidebar-chat-item";

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
}

const WORKSPACES: { id: WorkspaceId; label: string; icon: typeof MessageCircle }[] = [
  { id: "knowledge-chat", label: "Chat", icon: MessageCircle },
  { id: "image-generator", label: "Studio", icon: ImageIcon },
];

function groupByDate(conversations: { updatedAt: string; id: string }[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<string, string[]> = { Today: [], Yesterday: [], "Previous 7 days": [], Older: [] };
  for (const c of conversations) {
    const d = new Date(c.updatedAt);
    if (d >= today) groups["Today"].push(c.id);
    else if (d >= yesterday) groups["Yesterday"].push(c.id);
    else if (d >= weekAgo) groups["Previous 7 days"].push(c.id);
    else groups["Older"].push(c.id);
  }
  return groups;
}

export default function Sidebar({ isOpen }: SidebarProps) {
  const reduced = useReducedMotion();
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

  const sorted = useMemo(
    () => [...conversations].sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()),
    [conversations],
  );
  const filtered = useMemo(
    () => (search ? sorted.filter((c) => c.title.toLowerCase().includes(search.toLowerCase())) : sorted),
    [sorted, search],
  );
  const groups = useMemo(() => groupByDate(filtered), [filtered]);

  const initials = (user?.displayName || "Architect")
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.aside
          initial={reduced ? { width: 272, opacity: 1 } : { width: 0, opacity: 0 }}
          animate={{ width: 272, opacity: 1 }}
          exit={reduced ? { width: 0, opacity: 1 } : { width: 0, opacity: 0 }}
          transition={{ duration: reduced ? 0 : 0.2, ease: "easeInOut" }}
          className="h-screen flex flex-col overflow-hidden flex-shrink-0 bg-paper border-r border-hairline text-ink-deep font-sans"
        >
          {/* Brand */}
          <div className="px-4 pt-5 pb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-7 h-7 rounded-[7px] flex items-center justify-center text-[11px] font-mono font-semibold bg-ink-deep text-paper tracking-tagged">
                K
              </span>
              <span className="text-[15px] font-semibold text-ink-deep tracking-tight">
                Katha
              </span>
            </div>
          </div>

          {/* New chat + search + workspace */}
          <div className="px-3 space-y-1">
            <button
              onClick={() => createConversation()}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-hairline text-ink-deep hover:bg-paper-soft transition-colors text-[13px] font-medium"
            >
              <Plus size={14} strokeWidth={2.2} />
              New chat
              <span className="ml-auto px-1.5 py-0.5 rounded text-[10px] font-mono text-ink-mute tracking-wider">
                ⌘K
              </span>
            </button>

            <div className="relative">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-mute"
              />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search"
                className="w-full rounded-lg pl-9 pr-3 py-2 bg-transparent border border-transparent hover:bg-paper-soft focus:bg-paper-soft focus:border-hairline focus:outline-none transition-colors text-[13px] text-ink-deep placeholder:text-ink-mute"
              />
            </div>

            {WORKSPACES.map((ws) => {
              const Icon = ws.icon;
              const active = activeWorkspace === ws.id;
              return (
                <button
                  key={ws.id}
                  onClick={() => setActiveWorkspace(ws.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors text-[13px] ${
                    active
                      ? "bg-paper-soft text-ink-deep font-semibold"
                      : "text-ink-soft hover:bg-paper-soft hover:text-ink-deep font-medium"
                  }`}
                >
                  <Icon size={15} strokeWidth={1.8} />
                  {ws.label}
                </button>
              );
            })}
          </div>

          {/* Conversation list */}
          <div className="flex-1 overflow-y-auto draft-scroll px-2 pt-4 pb-2">
            {filtered.length === 0 ? (
              <div className="text-center py-10 px-4">
                <MessageSquare size={18} className="mx-auto mb-2 text-ink-mute opacity-50" />
                <p className="text-xs text-ink-mute">
                  {search ? "No matches" : "No conversations yet"}
                </p>
              </div>
            ) : (
              Object.entries(groups).map(
                ([label, ids]) =>
                  ids.length > 0 && (
                    <div key={label} className="mt-4 first:mt-0">
                      <p className="px-3 py-1 font-mono text-[10px] uppercase tracking-tagged text-ink-mute">
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

          {/* User footer */}
          <div className="p-3 border-t border-hairline">
            <div className="flex items-center gap-2.5 px-1">
              <div className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 bg-pencil-bg text-pencil border border-hairline font-mono text-[10.5px] font-semibold">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[12.5px] text-ink-deep font-medium tracking-tight">
                  {user?.displayName || "Architect"}
                </p>
                <p className="truncate text-[10.5px] text-ink-mute font-mono tracking-wider">
                  Free plan
                </p>
              </div>
            </div>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
