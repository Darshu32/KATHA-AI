"use client";

import { useCallback } from "react";
import { NotebookPen, Play } from "lucide-react";
import { useActiveNotebookSections, useNotesStore } from "@/lib/store";
import type { NoteBlockType } from "@/lib/types";
import NoteSectionHeader from "./note-section-header";
import NoteSectionImage from "./note-section-image";
import NoteSectionTags from "./note-section-tags";
import NoteBlock from "./note-block";
import AddBlockMenu from "./add-block-menu";
import MermaidDiagram from "@/components/chat/mermaid-diagram";

export default function NotebookView() {
  const sections = useActiveNotebookSections();
  const { searchQuery, addBlock, activeTagFilters } = useNotesStore();

  // Filter pipeline: search ⨯ tags. Both filters are AND-combined,
  // but the *tag* filter itself is OR-combined across the active
  // tags (a section is included if any of its tags appears in the
  // active filter set). This matches the dominant convention in
  // tag-based note apps (Notion, Bear, Obsidian) and feels less
  // restrictive than AND-across-tags.
  const filteredBySearch = searchQuery
    ? sections.filter((s) =>
        s.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.blocks.some((b) => b.content.toLowerCase().includes(searchQuery.toLowerCase())),
      )
    : sections;

  const filtered = activeTagFilters.length > 0
    ? filteredBySearch.filter((s) => {
        if (!s.tags || s.tags.length === 0) return false;
        const sectionTagsLower = s.tags.map((t) => t.toLowerCase());
        return activeTagFilters.some((f) =>
          sectionTagsLower.includes(f.toLowerCase()),
        );
      })
    : filteredBySearch;

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
          <div className="w-12 h-12 rounded-xl bg-paper-soft border border-hairline flex items-center justify-center mx-auto mb-3">
            <NotebookPen size={20} className="text-ink-mute" />
          </div>
          <p className="text-sm font-medium text-ink-soft mb-1">
            {searchQuery || activeTagFilters.length > 0
              ? "No matching notes"
              : "No notes yet"}
          </p>
          <p className="text-xs text-ink-mute leading-relaxed max-w-[200px]">
            {searchQuery || activeTagFilters.length > 0
              ? "Try a different search term or clear filters"
              : "Ask a deep question in the chat and notes will be auto-generated here"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto draft-scroll px-3 pb-6">
      {filtered.map((section) => (
        <div key={section.id} className="mb-4">
          <NoteSectionHeader
            sectionId={section.id}
            title={section.title}
            date={section.date}
          />

          {section.imageUrl && (
            <NoteSectionImage
              sectionId={section.id}
              imageUrl={section.imageUrl}
              alt={section.title}
            />
          )}

          {/* Deep-mode diagram — rendered as a real Mermaid figure, the same
              way it appears in the chat message. */}
          {section.diagram && (
            <div className="mb-1">
              <MermaidDiagram chart={section.diagram} />
            </div>
          )}

          {/* Deep-mode video — a "Watch on YouTube" card (thumbnail when we
              have a specific video, a play glyph for the search fallback). */}
          {section.video?.url && (
            <a
              href={section.video.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group mb-1.5 flex items-center gap-2 rounded-lg border border-hairline bg-paper-soft px-2.5 py-2 transition-colors hover:bg-paper-deep"
            >
              {section.video.thumbnail ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={section.video.thumbnail}
                  alt=""
                  className="h-10 w-16 flex-shrink-0 rounded object-cover"
                />
              ) : (
                <span className="flex h-10 w-16 flex-shrink-0 items-center justify-center rounded bg-[#ffe9e6]">
                  <Play size={16} className="text-[#e53e3e]" fill="#e53e3e" />
                </span>
              )}
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-[#e53e3e]">
                  <Play size={10} fill="#e53e3e" /> Watch on YouTube
                </span>
                <span className="block truncate text-xs text-ink-soft group-hover:text-ink-deep">
                  {section.video.title || "Related video"}
                </span>
              </span>
            </a>
          )}

          <NoteSectionTags sectionId={section.id} tags={section.tags ?? []} />

          <div className="pl-1">
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
