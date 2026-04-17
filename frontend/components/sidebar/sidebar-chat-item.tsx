"use client";

import { Trash2 } from "lucide-react";
import type { Conversation } from "@/lib/types";

interface SidebarChatItemProps {
  conversation: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d`;
  return new Date(dateStr).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function SidebarChatItem({
  conversation,
  isActive,
  onSelect,
  onDelete,
}: SidebarChatItemProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSelect();
      }}
      className="w-full text-left px-3 py-2 rounded-lg group transition-colors relative cursor-pointer"
      style={{
        backgroundColor: isActive ? "var(--paper-2)" : "transparent",
        fontFamily: "var(--sans)",
      }}
      onMouseEnter={(e) => {
        if (!isActive) e.currentTarget.style.backgroundColor = "var(--paper-2)";
      }}
      onMouseLeave={(e) => {
        if (!isActive) e.currentTarget.style.backgroundColor = "transparent";
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <p
          className="truncate flex-1"
          style={{
            fontSize: 13,
            fontWeight: isActive ? 600 : 500,
            color: isActive ? "var(--ink)" : "var(--ink-2)",
            letterSpacing: "-0.005em",
          }}
        >
          {conversation.title}
        </p>
        <div className="flex items-center gap-1 flex-shrink-0">
          <span
            className="group-hover:hidden"
            style={{ fontSize: 10.5, color: "var(--ink-3)", fontFamily: "var(--mono)", letterSpacing: "0.04em" }}
          >
            {timeAgo(conversation.updatedAt)}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="hidden group-hover:flex items-center justify-center w-6 h-6 rounded-md transition-colors"
            style={{ color: "var(--ink-3)" }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = "var(--accent)";
              e.currentTarget.style.backgroundColor = "var(--accent-soft)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "var(--ink-3)";
              e.currentTarget.style.backgroundColor = "transparent";
            }}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
