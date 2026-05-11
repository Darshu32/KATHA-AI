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
  const projectName = conversation.projectName?.trim();
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSelect();
      }}
      className={`w-full text-left px-3 py-2 rounded-lg group transition-colors relative cursor-pointer font-sans ${
        isActive ? "bg-paper-soft" : "hover:bg-paper-soft"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p
          className={`truncate flex-1 text-[13px] tracking-tight ${
            isActive ? "text-ink-deep font-semibold" : "text-ink-soft font-medium"
          }`}
        >
          {conversation.title}
        </p>
        <div className="flex items-center gap-1 flex-shrink-0">
          <span className="group-hover:hidden text-[10.5px] text-ink-mute font-mono tracking-wider tnum">
            {timeAgo(conversation.updatedAt)}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="hidden group-hover:flex items-center justify-center w-6 h-6 rounded-md text-ink-mute hover:text-pencil hover:bg-pencil-bg transition-colors"
            aria-label="Delete conversation"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>
      {/* Project caption — quiet, only when the chat is bound to a
       *  project. ``▸`` echoes the breadcrumb arrow used elsewhere in
       *  the design surface. */}
      {projectName ? (
        <p
          className="mt-0.5 truncate font-mono text-[10px] uppercase tracking-tagged text-ink-mute"
          title={`Project: ${projectName}`}
        >
          <span className="mr-1">▸</span>
          {projectName}
        </p>
      ) : null}
    </div>
  );
}
