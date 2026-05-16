"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  Download,
  FileText,
  NotebookPen,
  PanelRightClose,
  Search,
  X,
} from "lucide-react";
import { useChatStore, useImageGenStore } from "@/lib/store";
import { useActiveNotebookSections, useNotesStore } from "@/lib/store";
import {
  downloadTextFile,
  notebookToHTML,
  notebookToMarkdown,
  slugifyFilename,
} from "@/lib/notes-export";
import { toastError, useToastStore } from "@/lib/toast-store";
import { brief as briefApi } from "@/lib/api-client";
import NotebookView from "./notebook-view";
import ProjectBriefPanel from "./project-brief-panel";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export default function NotesSidebar({ isOpen, onClose }: Props) {
  const reduced = useReducedMotion();
  const router = useRouter();
  const {
    searchQuery,
    setSearchQuery,
    activeTagFilters,
    toggleTagFilter,
    clearTagFilters,
  } = useNotesStore();
  const sections = useActiveNotebookSections();
  const sectionCount = sections.length;
  const activeConversation = useChatStore((s) =>
    s.conversations.find((c) => c.id === s.activeConversationId) ?? null,
  );
  const [handoffPending, setHandoffPending] = useState(false);

  // BRD §1A → §3.6 handoff. When all 5 brief sections are confirmed,
  // ship the partial brief to the backend for canonicalisation, then
  // route to the design workspace with the resulting brief_id so it
  // can seed the first generation.
  async function handleReadyToDesign() {
    if (!activeConversation?.brief) return;
    if (handoffPending) return;
    setHandoffPending(true);
    try {
      const result = await briefApi.intake(activeConversation.brief);
      // Seed the design workspace store before navigating. We pass the
      // raw canonical-brief sections (already validated/normalised by
      // the backend) so the prompt-assembly helper has everything in
      // a known shape and we don't lose data in transit.
      useImageGenStore.getState().seedFromBrief(result.brief_id, {
        project_type: result.project_type,
        theme: result.theme,
        space: result.space,
        requirements: result.requirements,
        regulatory: result.regulatory,
      });
      useToastStore.getState().notify({
        type: "success",
        title: "Brief locked in",
        message: `Switching to design workspace (${result.brief_id.slice(0, 8)}…)`,
        durationMs: 3500,
      });
      router.push(`/design?brief_id=${encodeURIComponent(result.brief_id)}`);
    } catch (err) {
      toastError(err, "Could not validate brief");
    } finally {
      setHandoffPending(false);
    }
  }

  // Distinct tags across the active notebook, ordered by frequency
  // (most-used first) then alphabetically. Computing here rather than
  // in the store keeps the store dumb and lets us reuse memoisation
  // when the notebook hasn't changed.
  const allTags = useMemo(() => {
    const counts = new Map<string, { display: string; count: number }>();
    for (const sec of sections) {
      for (const t of sec.tags ?? []) {
        const key = t.toLowerCase();
        const cur = counts.get(key);
        if (cur) cur.count += 1;
        else counts.set(key, { display: t, count: 1 });
      }
    }
    return [...counts.values()]
      .sort((a, b) => b.count - a.count || a.display.localeCompare(b.display))
      .map((x) => x.display);
  }, [sections]);

  const activeTagSet = useMemo(
    () => new Set(activeTagFilters.map((t) => t.toLowerCase())),
    [activeTagFilters],
  );

  // ``exportingPdf`` blocks a second click while jspdf is doing its
  // (synchronously-blocking) render pass. PDFs of moderate notebooks
  // take ~1–3 seconds; without the guard a user double-click queues
  // two renders and the second one fights for the same hidden DOM
  // node.
  const [exportingPdf, setExportingPdf] = useState(false);

  const notebookTitle =
    (activeConversation?.title && activeConversation.title !== "New conversation"
      ? activeConversation.title
      : "Notes") || "Notes";

  function handleDownloadMarkdown() {
    if (sections.length === 0) return;
    const md = notebookToMarkdown(sections, notebookTitle);
    downloadTextFile(`${slugifyFilename(notebookTitle)}.md`, md);
  }

  async function handleDownloadPDF() {
    if (sections.length === 0 || exportingPdf) return;
    setExportingPdf(true);
    try {
      // jspdf's ESM build is large (~700kB) — load on demand so it's
      // not in the initial route bundle. The dynamic import is
      // resolved by Next's chunk splitter.
      const { default: jsPDF } = await import("jspdf");

      const doc = new jsPDF({
        unit: "pt",
        format: "a4",
        orientation: "portrait",
      });

      // Render to an off-screen container. We can't use display:none —
      // jspdf.html() needs computed layout. Push it far off-canvas
      // instead, with a fixed width matching the printed page area
      // (A4 minus margins ≈ 515pt ≈ 686px at 96dpi).
      const host = document.createElement("div");
      host.style.position = "fixed";
      host.style.top = "-10000px";
      host.style.left = "0";
      host.style.width = "686px";
      host.style.background = "#ffffff";
      host.innerHTML = notebookToHTML(sections, notebookTitle);
      document.body.appendChild(host);

      try {
        await doc.html(host, {
          // Margins in points (72pt = 1in). A4 is 595x842pt.
          margin: [40, 36, 40, 36],
          // Auto-paginate when content overflows.
          autoPaging: "text",
          // Scale: ratio of PDF unit width to source HTML width.
          // 515pt page area / 686px source = ~0.751.
          html2canvas: {
            scale: 0.751,
            backgroundColor: "#ffffff",
            // Avoid CORS taint from any inlined images we don't ship
            // yet (images-in-notes is a future phase).
            useCORS: true,
          },
        });
        doc.save(`${slugifyFilename(notebookTitle)}.pdf`);
      } finally {
        host.remove();
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[notes] PDF export failed", err);
    } finally {
      setExportingPdf(false);
    }
  }

  return (
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.aside
          // Reduced-motion users skip the width animation — the panel
          // simply appears with full width and opacity. The
          // ``AnimatePresence`` still controls mount/unmount so the
          // panel doesn't pop in/out without a frame.
          initial={reduced ? { width: 320, opacity: 1 } : { width: 0, opacity: 0 }}
          animate={{ width: 320, opacity: 1 }}
          exit={reduced ? { width: 0, opacity: 1 } : { width: 0, opacity: 0 }}
          transition={{ duration: reduced ? 0 : 0.2, ease: "easeInOut" }}
          className="h-full bg-paper border-l border-hairline flex flex-col overflow-hidden flex-shrink-0"
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-hairline flex-shrink-0">
            <div className="flex items-center justify-between mb-2.5">
              <div className="flex items-center gap-2">
                <NotebookPen size={16} className="text-ink-soft" />
                <span className="text-sm font-semibold text-ink-deep">Notes</span>
                {sectionCount > 0 && (
                  <span className="text-[10px] bg-paper-deep text-ink-soft px-1.5 py-0.5 rounded-full font-mono tnum">
                    {sectionCount}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-0.5">
                {/* Export buttons. Disabled when the notebook is
                 *  empty so they don't trigger an empty-file
                 *  download. PDF button shows a brief disabled
                 *  state during render to prevent double-clicks
                 *  from queuing two renders. */}
                <button
                  onClick={handleDownloadMarkdown}
                  disabled={sectionCount === 0}
                  className="p-1.5 text-ink-mute hover:text-ink-deep rounded-lg hover:bg-paper-soft transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-ink-mute disabled:cursor-not-allowed"
                  title="Download notebook as Markdown"
                  aria-label="Download notebook as Markdown"
                >
                  <Download size={15} />
                </button>
                <button
                  onClick={handleDownloadPDF}
                  disabled={sectionCount === 0 || exportingPdf}
                  className="p-1.5 text-ink-mute hover:text-ink-deep rounded-lg hover:bg-paper-soft transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-ink-mute disabled:cursor-not-allowed"
                  title={exportingPdf ? "Generating PDF…" : "Download notebook as PDF"}
                  aria-label="Download notebook as PDF"
                >
                  <FileText size={15} />
                </button>
                <button
                  onClick={onClose}
                  className="p-1.5 text-ink-mute hover:text-ink rounded-lg hover:bg-paper-soft transition-colors"
                  title="Close notes panel"
                  aria-label="Close notes panel"
                >
                  <PanelRightClose size={16} />
                </button>
              </div>
            </div>

            {/* Search */}
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-mute" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search notes..."
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-paper-soft border border-hairline rounded-lg text-ink placeholder:text-ink-mute focus:outline-none focus:border-graphite focus:bg-paper transition-colors"
              />
            </div>

            {/* Tag filter chips. Hidden when no tags exist in the
             *  active notebook so empty notebooks don't waste vertical
             *  space on a row that says nothing. */}
            {allTags.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1">
                {allTags.map((tag) => {
                  const active = activeTagSet.has(tag.toLowerCase());
                  return (
                    <button
                      key={tag.toLowerCase()}
                      onClick={() => toggleTagFilter(tag)}
                      className={
                        "text-[10px] font-medium px-1.5 py-0.5 rounded-full transition-colors " +
                        (active
                          ? "bg-ink-deep text-paper hover:bg-ink"
                          : "bg-paper-deep text-ink-soft hover:bg-paper-edge")
                      }
                      title={active ? `Remove #${tag} filter` : `Filter by #${tag}`}
                    >
                      #{tag}
                    </button>
                  );
                })}
                {activeTagFilters.length > 0 && (
                  <button
                    onClick={clearTagFilters}
                    className="inline-flex items-center gap-0.5 text-[10px] text-ink-mute hover:text-pencil px-1 py-0.5 rounded transition-colors"
                    title="Clear tag filters"
                    aria-label="Clear tag filters"
                  >
                    <X size={10} /> clear
                  </button>
                )}
              </div>
            )}
          </div>

          {/* BRD §1A — Project Brief panel pinned above the notebook.
              Self-hides until the agent captures something. */}
          <ProjectBriefPanel
            brief={activeConversation?.brief}
            status={activeConversation?.briefStatus}
            missing={activeConversation?.briefMissing}
            onReadyToDesign={handleReadyToDesign}
            readyDisabled={handoffPending}
          />

          {/* Content */}
          <NotebookView />

          {/* Footer hint */}
          <div className="px-4 py-2 border-t border-hairline flex-shrink-0">
            <p className="text-[10px] text-ink-mute text-center">
              Deep mode conversations auto-generate notes
            </p>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
