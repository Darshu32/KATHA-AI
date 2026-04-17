"use client";

import { useCallback } from "react";
import { NotebookPen } from "lucide-react";
import { useNotesStore } from "@/lib/store";
import type { NoteBlockType } from "@/lib/types";
import NoteSectionHeader from "./note-section-header";
import NoteBlock from "./note-block";
import AddBlockMenu from "./add-block-menu";

export default function NotebookView() {
  const { notebook, searchQuery, addBlock } = useNotesStore();

  const filtered = searchQuery
    ? notebook.sections.filter((s) =>
        s.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.blocks.some((b) => b.content.toLowerCase().includes(searchQuery.toLowerCase())),
      )
    : notebook.sections;

  const handleAddBlock = useCallback(
    (sectionId: string, afterBlockId: string | null, type: NoteBlockType) => {
      const block = {
        id: crypto.randomUUID(),
        type,
        content: "",
        indent: 0,
        createdAt: new Date().toISOString(),
        ...(type === "callout" ? { calloutVariant: "info" as const } : {}),
      };
      addBlock(sectionId, afterBlockId, block);
    },
    [addBlock],
  );

  if (filtered.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="text-center">
          <div className="w-12 h-12 rounded-xl bg-gray-50 border border-gray-100 flex items-center justify-center mx-auto mb-3">
            <NotebookPen size={20} className="text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600 mb-1">
            {searchQuery ? "No matching notes" : "No notes yet"}
          </p>
          <p className="text-xs text-gray-400 leading-relaxed max-w-[200px]">
            {searchQuery
              ? "Try a different search term"
              : "Ask a deep question in the chat and notes will be auto-generated here"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto chat-scrollbar px-3 pb-6">
      {filtered.map((section) => (
        <div key={section.id} className="mb-4">
          <NoteSectionHeader
            sectionId={section.id}
            title={section.title}
            date={section.date}
          />

          <div className="mt-1.5 pl-1">
            {/* Add block at top */}
            <AddBlockMenu onAdd={(type) => handleAddBlock(section.id, null, type)} />

            {section.blocks.map((block, idx) => (
              <div key={block.id}>
                <NoteBlock
                  block={block}
                  sectionId={section.id}
                  index={idx}
                  onAddAfter={(afterId) => handleAddBlock(section.id, afterId, "paragraph")}
                />
                {/* Add block between blocks */}
                <AddBlockMenu onAdd={(type) => handleAddBlock(section.id, block.id, type)} />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
