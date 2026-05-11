"use client";

import { useState } from "react";
import { Check, Copy, MessageCircle, Trash2 } from "lucide-react";
import { useActiveNotebookSections, useNotesStore } from "@/lib/store";
import {
  copyToClipboard,
  sectionToMarkdown,
} from "@/lib/notes-export";

interface Props {
  sectionId: string;
  title: string;
  date: string;
}

export default function NoteSectionHeader({ sectionId, title, date }: Props) {
  const { deleteSection } = useNotesStore();
  const sections = useActiveNotebookSections();
  const [confirmDelete, setConfirmDelete] = useState(false);
  // ``copied`` flips to true on a successful copy and resets after a
  // short delay so the user gets visual confirmation. Using a number
  // (timestamp) instead of bool would let us cancel an in-flight
  // reset cleanly on rapid re-clicks; a boolean is enough for v1.
  const [copied, setCopied] = useState(false);

  const formatted = new Date(date).toLocaleDateString("en-IN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  async function handleCopy() {
    const section = sections.find((s) => s.id === sectionId);
    if (!section) return;
    const ok = await copyToClipboard(sectionToMarkdown(section));
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }
  }

  return (
    <div className="flex items-center justify-between px-1 py-2 mt-3 first:mt-0 border-b border-hairline group">
      <div className="flex items-center gap-2 min-w-0">
        <MessageCircle size={12} className="text-ink-mute flex-shrink-0" />
        <span className="text-xs font-semibold text-ink-deep truncate">{title}</span>
        <span className="text-[10px] text-ink-mute flex-shrink-0 tnum">{formatted}</span>
      </div>
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {/* Copy as Markdown — quiet, on-hover, with a brief confirm
         *  state. Stays visible if the user clicks while the confirm
         *  is showing because ``copied`` keeps the icon highlighted.
         */}
        <button
          onClick={handleCopy}
          title={copied ? "Copied!" : "Copy section as Markdown"}
          aria-label="Copy section as Markdown"
          className={
            "p-0.5 rounded transition-colors " +
            (copied
              ? "text-olive"
              : "text-ink-mute hover:text-ink-deep")
          }
        >
          {copied ? <Check size={11} /> : <Copy size={11} />}
        </button>

        {confirmDelete ? (
          <div className="flex items-center gap-1">
            <button
              onClick={() => deleteSection(sectionId)}
              className="text-[10px] text-pencil hover:text-pencil-soft font-medium"
            >
              Delete
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="text-[10px] text-ink-mute hover:text-ink"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="p-0.5 text-ink-mute hover:text-pencil rounded"
            title="Delete section"
            aria-label="Delete section"
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>
    </div>
  );
}
