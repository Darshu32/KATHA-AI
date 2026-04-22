"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
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
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 272, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="h-screen flex flex-col overflow-hidden flex-shrink-0"
          style={{
            backgroundColor: "var(--paper)",
            borderRight: "1px solid var(--rule)",
            fontFamily: "var(--sans)",
            color: "var(--ink)",
          }}
        >
          {/* Brand + workspace switch */}
          <div className="px-4 pt-5 pb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span
                className="w-7 h-7 rounded-[7px] flex items-center justify-center text-[11px]"
                style={{
                  backgroundColor: "var(--ink)",
                  color: "var(--paper)",
                  fontFamily: "var(--mono)",
                  fontWeight: 600,
                  letterSpacing: "0.06em",
                }}
              >
                K
              </span>
              <span style={{ fontWeight: 600, fontSize: 15, letterSpacing: "-0.015em" }}>
                Katha
              </span>
            </div>
          </div>

          {/* New chat + search */}
          <div className="px-3 space-y-1">
            <button
              onClick={() => createConversation()}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg transition-colors"
              style={{
                backgroundColor: "transparent",
                border: "1px solid var(--rule)",
                color: "var(--ink)",
                fontSize: 13,
                fontWeight: 500,
                letterSpacing: "-0.005em",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--paper-2)")}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
            >
              <Plus size={14} strokeWidth={2.2} />
              New chat
              <span
                className="ml-auto px-1.5 py-0.5 rounded text-[10px] tracking-wider"
                style={{ color: "var(--ink-3)", fontFamily: "var(--mono)" }}
              >
                ⌘K
              </span>
            </button>

            <div className="relative">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2"
                style={{ color: "var(--ink-3)" }}
              />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search"
                className="w-full rounded-lg pl-9 pr-3 py-2 focus:outline-none transition-colors"
                style={{
                  backgroundColor: "transparent",
                  border: "1px solid transparent",
                  fontSize: 13,
                  color: "var(--ink)",
                  fontFamily: "var(--sans)",
                }}
                onFocus={(e) => (e.currentTarget.style.borderColor = "var(--rule)")}
                onBlur={(e) => (e.currentTarget.style.borderColor = "transparent")}
                onMouseEnter={(e) => {
                  if (document.activeElement !== e.currentTarget)
                    e.currentTarget.style.backgroundColor = "var(--paper-2)";
                }}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
              />
            </div>

            {WORKSPACES.map((ws) => {
              const Icon = ws.icon;
              const active = activeWorkspace === ws.id;
              return (
                <button
                  key={ws.id}
                  onClick={() => setActiveWorkspace(ws.id)}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors"
                  style={{
                    backgroundColor: active ? "var(--paper-2)" : "transparent",
                    color: "var(--ink)",
                    fontSize: 13,
                    fontWeight: active ? 600 : 500,
                  }}
                  onMouseEnter={(e) => {
                    if (!active) e.currentTarget.style.backgroundColor = "var(--paper-2)";
                  }}
                  onMouseLeave={(e) => {
                    if (!active) e.currentTarget.style.backgroundColor = "transparent";
                  }}
                >
                  <Icon size={15} strokeWidth={1.8} />
                  {ws.label}
                </button>
              );
            })}
          </div>

          {/* Conversation list */}
          <div className="flex-1 overflow-y-auto chat-scrollbar px-2 pt-4 pb-2">
            {filtered.length === 0 ? (
              <div className="text-center py-10 px-4">
                <MessageSquare size={18} style={{ color: "var(--ink-3)" }} className="mx-auto mb-2 opacity-50" />
                <p style={{ fontSize: 12, color: "var(--ink-3)" }}>
                  {search ? "No matches" : "No conversations yet"}
                </p>
              </div>
            ) : (
              Object.entries(groups).map(
                ([label, ids]) =>
                  ids.length > 0 && (
                    <div key={label} className="mt-4 first:mt-0">
                      <p
                        className="px-3 py-1"
                        style={{
                          fontFamily: "var(--mono)",
                          fontSize: 10,
                          letterSpacing: "0.22em",
                          textTransform: "uppercase",
                          color: "var(--ink-3)",
                        }}
                      >
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

          {/* Minimal user footer */}
          <div className="p-3" style={{ borderTop: "1px solid var(--rule)" }}>
            <div className="flex items-center gap-2.5 px-1">
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
                style={{
                  backgroundColor: "var(--accent-soft)",
                  color: "var(--accent-2)",
                  fontFamily: "var(--mono)",
                  fontSize: 10.5,
                  fontWeight: 600,
                  letterSpacing: "0.02em",
                  border: "1px solid var(--rule)",
                }}
              >
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p
                  className="truncate"
                  style={{ fontSize: 12.5, color: "var(--ink)", fontWeight: 500, letterSpacing: "-0.005em" }}
                >
                  {user?.displayName || "Architect"}
                </p>
                <p
                  className="truncate"
                  style={{ fontSize: 10.5, color: "var(--ink-3)", fontFamily: "var(--mono)", letterSpacing: "0.02em" }}
                >
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
