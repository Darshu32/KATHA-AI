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
  return new Date(dateStr).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export default function SidebarChatItem({
  conversation,
  isActive,
  onSelect,
  onDelete,
}: SidebarChatItemProps) {
  const lastMessage = conversation.messages[conversation.messages.length - 1];
  const preview = lastMessage
    ? lastMessage.content.slice(0, 50) + (lastMessage.content.length > 50 ? "..." : "")
    : "Empty conversation";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === "Enter") onSelect(); }}
      className={`w-full text-left px-3 py-2.5 rounded-lg group transition-colors relative cursor-pointer ${
        isActive ? "bg-gray-100" : "hover:bg-gray-50"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-800 truncate">
            {conversation.title}
          </p>
          <p className="text-xs text-gray-400 truncate mt-0.5">{preview}</p>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <span className="text-xs text-gray-400 group-hover:hidden">
            {timeAgo(conversation.updatedAt)}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="hidden group-hover:flex items-center justify-center w-6 h-6 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
