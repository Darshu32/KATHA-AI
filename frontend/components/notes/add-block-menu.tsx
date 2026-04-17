"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import type { NoteBlockType } from "@/lib/types";

interface Props {
  onAdd: (type: NoteBlockType) => void;
}

const OPTIONS: { type: NoteBlockType; label: string; desc: string }[] = [
  { type: "paragraph", label: "Text", desc: "Plain text" },
  { type: "heading-2", label: "Heading", desc: "Section heading" },
  { type: "bullet-list", label: "Bullet", desc: "Bullet point" },
  { type: "numbered-list", label: "Number", desc: "Numbered item" },
  { type: "callout", label: "Callout", desc: "Highlighted note" },
  { type: "toggle", label: "Toggle", desc: "Collapsible block" },
  { type: "divider", label: "Divider", desc: "Horizontal line" },
];

export default function AddBlockMenu({ onAdd }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative flex justify-center py-0.5 opacity-0 hover:opacity-100 transition-opacity">
      <button
        onClick={() => setOpen(!open)}
        className="p-0.5 text-gray-300 hover:text-gray-500 hover:bg-gray-100 rounded transition-colors"
        title="Add block"
      >
        <Plus size={12} />
      </button>
      {open && (
        <div className="absolute top-5 left-1/2 -translate-x-1/2 z-20 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-36">
          {OPTIONS.map((opt) => (
            <button
              key={opt.type}
              onClick={() => {
                onAdd(opt.type);
                setOpen(false);
              }}
              className="w-full text-left px-3 py-1.5 hover:bg-gray-50 transition-colors"
            >
              <span className="text-xs font-medium text-gray-700">{opt.label}</span>
              <span className="text-[10px] text-gray-400 ml-1.5">{opt.desc}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
