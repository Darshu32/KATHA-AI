"use client";

import { useState } from "react";
import { Trash2, MessageCircle } from "lucide-react";
import { useNotesStore } from "@/lib/store";

interface Props {
  sectionId: string;
  title: string;
  date: string;
}

export default function NoteSectionHeader({ sectionId, title, date }: Props) {
  const { deleteSection } = useNotesStore();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const formatted = new Date(date).toLocaleDateString("en-IN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="flex items-center justify-between px-1 py-2 mt-3 first:mt-0 border-b border-gray-100 group">
      <div className="flex items-center gap-2 min-w-0">
        <MessageCircle size={12} className="text-gray-400 flex-shrink-0" />
        <span className="text-xs font-semibold text-gray-700 truncate">{title}</span>
        <span className="text-[10px] text-gray-400 flex-shrink-0">{formatted}</span>
      </div>
      <div className="opacity-0 group-hover:opacity-100 transition-opacity">
        {confirmDelete ? (
          <div className="flex items-center gap-1">
            <button
              onClick={() => deleteSection(sectionId)}
              className="text-[10px] text-red-500 hover:text-red-700 font-medium"
            >
              Delete
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="text-[10px] text-gray-400 hover:text-gray-600"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="p-0.5 text-gray-300 hover:text-red-400 rounded"
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>
    </div>
  );
}
