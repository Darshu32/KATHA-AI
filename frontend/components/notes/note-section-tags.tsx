"use client";

/**
 * NoteSectionTags — inline tag editor for a single note section.
 *
 * Renders existing tags as compact pills (with hover-X to remove),
 * followed by a "+ tag" pill that expands into a small text input.
 * Commits on Enter or blur; cancels on Escape. Whitespace is trimmed
 * and case-insensitive duplicates are silently dropped (mirrors the
 * server's canonicalisation).
 *
 * Why this lives next to the header instead of inside it
 * ------------------------------------------------------
 * Tag editing wants to wrap and grow vertically when the user adds
 * more tags than fit on one row. The header is a single-line flex
 * container with truncation; cramming tags into it would either
 * truncate them or push the title off-screen. A separate row is
 * cleaner and matches how Notion / Obsidian render section
 * metadata.
 */

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Plus, X } from "lucide-react";
import { useNotesStore } from "@/lib/store";

interface Props {
  sectionId: string;
  tags: string[];
}

export default function NoteSectionTags({ sectionId, tags }: Props) {
  const addTagToSection = useNotesStore((s) => s.addTagToSection);
  const removeTagFromSection = useNotesStore((s) => s.removeTagFromSection);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Auto-focus the input the moment we enter editing mode. ``setTimeout``
  // is needed because the input doesn't exist on the same tick the
  // state flips — we wait for React to mount it.
  useEffect(() => {
    if (editing) {
      const t = setTimeout(() => inputRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
  }, [editing]);

  function commit() {
    const v = draft.trim();
    if (v) addTagToSection(sectionId, v);
    setDraft("");
    setEditing(false);
  }

  function cancel() {
    setDraft("");
    setEditing(false);
  }

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    } else if (e.key === "Backspace" && !draft && tags.length > 0) {
      // Empty-input backspace removes the last tag — a tiny power-user
      // affordance that costs nothing and feels right in tag UIs.
      removeTagFromSection(sectionId, tags[tags.length - 1]);
    }
  }

  if (tags.length === 0 && !editing) {
    // Compact resting state: just a quiet "+ tag" pill.
    return (
      <div className="px-1 mb-1.5">
        <button
          onClick={() => setEditing(true)}
          className="inline-flex items-center gap-1 text-[10px] text-ink-mute hover:text-ink-deep px-1.5 py-0.5 rounded-full border border-dashed border-graphite hover:border-ink-soft transition-colors"
          title="Add a tag"
        >
          <Plus size={9} />
          tag
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1 px-1 mb-1.5">
      {tags.map((t) => (
        <span
          key={t.toLowerCase()}
          className="group/tag inline-flex items-center gap-0.5 text-[10px] font-medium bg-paper-deep hover:bg-paper-edge text-ink-deep px-1.5 py-0.5 rounded-full transition-colors"
        >
          <span>#{t}</span>
          <button
            onClick={() => removeTagFromSection(sectionId, t)}
            className="opacity-0 group-hover/tag:opacity-100 hover:text-pencil transition-opacity"
            title={`Remove tag #${t}`}
            aria-label={`Remove tag ${t}`}
          >
            <X size={9} />
          </button>
        </span>
      ))}

      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKey}
          onBlur={commit}
          maxLength={40}
          placeholder="tag"
          className="text-[10px] bg-transparent border-b border-graphite px-1 py-0 w-20 outline-none focus:border-ink-deep"
        />
      ) : (
        <button
          onClick={() => setEditing(true)}
          className="inline-flex items-center gap-0.5 text-[10px] text-ink-mute hover:text-ink-deep px-1.5 py-0.5 rounded-full border border-dashed border-graphite hover:border-ink-soft transition-colors"
          title="Add a tag"
          aria-label="Add a tag"
        >
          <Plus size={9} />
        </button>
      )}
    </div>
  );
}
