/**
 * Notes export — serialize ``NoteSection`` data to portable formats.
 *
 * Phase 2 of the Notes feature: get notes *out* of the app. Three
 * surfaces use these:
 *
 * - **Copy as Markdown** (per section) — clipboard, zero deps.
 * - **Download as Markdown** (whole notebook) — Blob download.
 * - **Download as PDF** (whole notebook) — feeds the rendered
 *   markdown HTML into ``jspdf.html()``; that route is wired in
 *   the sidebar component, not here, because it touches the DOM.
 *
 * Why this lives in /lib (not /components)
 * ----------------------------------------
 * Pure transforms. No React, no DOM. Easy to unit-test. The
 * components that *trigger* export (buttons, file save dialogs) own
 * the side-effects.
 *
 * Markdown dialect
 * ----------------
 * Targets CommonMark + GFM (the same flavor ``react-markdown`` +
 * ``remark-gfm`` already render in the chat). That means readers
 * (Notion, Obsidian, GitHub, VS Code, Bear) all render the output
 * identically to what the user sees in the app — modulo a few app-
 * specific block types that have no native markdown equivalent
 * (``toggle``, ``callout``). Those degrade gracefully:
 *
 * - ``toggle`` → bold heading then nested children. Loses
 *   collapsibility but preserves hierarchy.
 * - ``callout`` → blockquote prefixed with a single emoji-tagged
 *   marker so the reader knows it was emphasised in the original.
 */

import type { NoteBlock, NoteSection, CalloutVariant } from "./types";

// ── Block-level rendering ──────────────────────────────────────────────

const CALLOUT_PREFIX: Record<CalloutVariant, string> = {
  info: "ℹ️ Note:",
  tip: "💡 Tip:",
  warning: "⚠️ Warning:",
  important: "❗ Important:",
};

/** Indent prefix for a nested block (2 spaces per level — matches
 *  the canonical CommonMark convention for list-item continuation). */
function indent(level: number): string {
  return "  ".repeat(Math.max(0, level));
}

/** Serialize one block to one or more markdown lines. The caller
 *  joins the result with single newlines; block separators (blank
 *  lines) are decided at the section level. */
function blockToMarkdown(block: NoteBlock): string {
  const pad = indent(block.indent);
  const content = (block.content ?? "").trim();

  switch (block.type) {
    case "heading-1":
      return `${pad}# ${content}`;
    case "heading-2":
      return `${pad}## ${content}`;
    case "heading-3":
      return `${pad}### ${content}`;

    case "paragraph":
      return content ? `${pad}${content}` : "";

    case "bullet-list":
      return `${pad}- ${content}`;

    case "numbered-list":
      // We can't recover the original ordinal from a flat block list
      // (each list item is its own block). Markdown is happy with all
      // ``1.`` — most renderers auto-renumber on display.
      return `${pad}1. ${content}`;

    case "divider":
      return `${pad}---`;

    case "callout": {
      const prefix = CALLOUT_PREFIX[block.calloutVariant ?? "info"];
      // Multi-line callouts get the blockquote marker on each line
      // so the reader applies the quote style to the whole block.
      const lines = content.split("\n").map((l, i) =>
        i === 0 ? `${pad}> ${prefix} ${l}` : `${pad}> ${l}`,
      );
      return lines.join("\n");
    }

    case "toggle": {
      // Toggles have no native markdown. Render as a bold heading
      // followed by indented children (if any). Collapsibility is
      // lost on export — most readers will show all children
      // expanded, which is what the user wants from a snapshot.
      const head = `${pad}**${content}**`;
      const kids = (block.children ?? []).map(blockToMarkdown).filter(Boolean);
      return [head, ...kids].join("\n");
    }
  }
}

// ── Section-level rendering ────────────────────────────────────────────

/** Serialize one section to a self-contained markdown document. */
export function sectionToMarkdown(section: NoteSection): string {
  const dateStr = formatHumanDate(section.date);

  // Section header: H1 title + italic date line + tag line (if any)
  // + image (if any).
  // We render tags as ``Tags: #vastu #villa`` rather than a YAML
  // front-matter block — works in every markdown reader, and since
  // ``#`` already means "heading" in markdown only at line-start, an
  // inline tag in the middle of a line stays as plain text.
  const lines: string[] = [`# ${section.title}`, `*${dateStr}*`];
  if (section.tags && section.tags.length > 0) {
    const tagStr = section.tags.map((t) => `\`#${t}\``).join(" ");
    lines.push(`Tags: ${tagStr}`);
  }
  // Image (Phase 4). The data URI works in every markdown renderer
  // we care about; readers that don't support inline images simply
  // show the alt text. We deliberately use the section title as alt
  // text (rather than "image") so screen readers get something
  // meaningful.
  if (section.imageUrl) {
    lines.push("");
    lines.push(`![${section.title}](${section.imageUrl})`);
  }
  lines.push("");

  // Each block on its own paragraph block. Blank line between
  // adjacent block outputs preserves "paragraph-ness" in markdown
  // — except inside list runs, where the blank line would break the
  // list. We pragmatically *omit* the separator when both adjacent
  // blocks are list items at the same indent.
  let prev: NoteBlock | null = null;
  for (const block of section.blocks) {
    const rendered = blockToMarkdown(block);
    if (!rendered) {
      prev = block;
      continue;
    }
    const tightWithPrev =
      prev !== null &&
      isListBlock(prev) &&
      isListBlock(block) &&
      prev.type === block.type &&
      prev.indent === block.indent;
    if (lines.length > 0 && !tightWithPrev) {
      lines.push("");
    }
    lines.push(rendered);
    prev = block;
  }

  // Trim trailing blanks, end with a single newline.
  while (lines.length && lines[lines.length - 1] === "") lines.pop();
  return lines.join("\n") + "\n";
}

/** Serialize a whole notebook (every section in a conversation) to
 *  one markdown document. Sections are separated by a horizontal
 *  rule + blank line — readable both raw and rendered. */
export function notebookToMarkdown(
  sections: NoteSection[],
  notebookTitle?: string,
): string {
  if (sections.length === 0) {
    return notebookTitle
      ? `# ${notebookTitle}\n\n*No notes yet.*\n`
      : `*No notes yet.*\n`;
  }
  const parts: string[] = [];
  if (notebookTitle) {
    parts.push(`# ${notebookTitle}`, "");
  }
  parts.push(sections.map(sectionToMarkdown).join("\n---\n\n"));
  return parts.join("\n");
}

// ── Browser-side download helpers ──────────────────────────────────────

/** Trigger a file download from a string blob. Safe in any modern
 *  browser; bails out silently when called server-side (build-time
 *  static rendering). */
export function downloadTextFile(
  filename: string,
  contents: string,
  mimeType = "text/markdown;charset=utf-8",
): void {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  const blob = new Blob([contents], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // Some browsers require the anchor to be in the DOM.
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Free the object URL after the click has been processed.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Copy a string to the clipboard. Returns true on success.
 *  Uses the modern async clipboard API; falls back to nothing if
 *  unavailable (older browsers, insecure context). */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator === "undefined" || !navigator.clipboard) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

// ── Internals ──────────────────────────────────────────────────────────

function isListBlock(b: NoteBlock): boolean {
  return b.type === "bullet-list" || b.type === "numbered-list";
}

/** Format an ISO timestamp as a short human date.
 *  Uses ``en-US`` so output is stable across locales — exports are a
 *  document the user might share, and a fixed date format is more
 *  predictable than the browser's current locale. */
function formatHumanDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

// ── HTML rendering (for PDF export) ────────────────────────────────────
//
// We render directly from the block structure rather than going
// through a markdown→HTML pipeline. Reasons:
//   1. We have richer information (callout variants, toggle children)
//      than markdown can express, so a direct render preserves it.
//   2. No runtime dependency on a markdown parser inside the export
//      hot path — keeps the bundle small.
//   3. We can hand-tune typography for print output, which is
//      different from the on-screen styling.
//
// The output is a self-contained HTML document with inlined styles
// (no external CSS) so it renders identically inside ``jspdf.html()``,
// which spawns its own context.

const CALLOUT_HTML_STYLES: Record<CalloutVariant, { bg: string; border: string }> = {
  info: { bg: "#eff6ff", border: "#3b82f6" },
  tip: { bg: "#f0fdf4", border: "#22c55e" },
  warning: { bg: "#fef3c7", border: "#f59e0b" },
  important: { bg: "#fef2f2", border: "#ef4444" },
};

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Render minimal inline markdown — ``**bold**`` and ``*italic*`` —
 *  to HTML. Anything else is passed through escaped. The chat
 *  pipeline emits these markers, so respecting them here keeps the
 *  exported PDF readable. */
function renderInline(text: string): string {
  const escaped = escapeHtml(text);
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
}

function blockToHTML(block: NoteBlock): string {
  const indentPx = (block.indent ?? 0) * 16;
  const style = indentPx ? ` style="margin-left:${indentPx}px"` : "";
  const inner = renderInline(block.content ?? "");

  switch (block.type) {
    case "heading-1":
      return `<h1${style}>${inner}</h1>`;
    case "heading-2":
      return `<h2${style}>${inner}</h2>`;
    case "heading-3":
      return `<h3${style}>${inner}</h3>`;
    case "paragraph":
      return inner ? `<p${style}>${inner}</p>` : "";
    case "bullet-list":
      // Single-item lists. The grouping pass below merges runs.
      return `<li${style}>${inner}</li>`;
    case "numbered-list":
      return `<li${style}>${inner}</li>`;
    case "divider":
      return `<hr${style} />`;
    case "callout": {
      const variant = block.calloutVariant ?? "info";
      const palette = CALLOUT_HTML_STYLES[variant];
      const prefix = CALLOUT_PREFIX[variant];
      return `<div${style ? ` style="${style.slice(8, -1)};` : ' style="'}background:${palette.bg};border-left:3px solid ${palette.border};padding:8px 12px;margin:8px 0;border-radius:4px"><strong>${escapeHtml(prefix)}</strong> ${inner}</div>`;
    }
    case "toggle": {
      const head = `<p${style}><strong>${inner}</strong></p>`;
      const kids = (block.children ?? []).map(blockToHTML).filter(Boolean).join("");
      return head + kids;
    }
  }
}

/** Wrap consecutive list-item blocks in a single ``<ul>``/``<ol>``
 *  so PDF readers render them as proper lists rather than orphan
 *  ``<li>`` tags floating in flow content. */
function blocksToHTML(blocks: NoteBlock[]): string {
  const out: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let listIndent = 0;

  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`);
      listType = null;
    }
  };

  for (const block of blocks) {
    const isBullet = block.type === "bullet-list";
    const isNumbered = block.type === "numbered-list";

    if (isBullet || isNumbered) {
      const want: "ul" | "ol" = isBullet ? "ul" : "ol";
      if (listType !== want || listIndent !== block.indent) {
        closeList();
        listType = want;
        listIndent = block.indent;
        out.push(`<${want} style="margin:6px 0;padding-left:24px">`);
      }
    } else {
      closeList();
    }

    const html = blockToHTML(block);
    if (html) out.push(html);
  }
  closeList();
  return out.join("");
}

/** A self-contained HTML document for one notebook. Inlined styles
 *  only — no <link> tags — so it renders the same in ``jspdf.html()``
 *  as in a browser. */
export function notebookToHTML(
  sections: NoteSection[],
  notebookTitle: string,
): string {
  const sectionHtml = sections
    .map((s) => {
      const date = formatHumanDate(s.date);
      const blocks = blocksToHTML(s.blocks);
      const tagsHtml =
        s.tags && s.tags.length > 0
          ? `<div style="margin:0 0 10px 0">${s.tags
              .map(
                (t) =>
                  `<span style="display:inline-block;font-size:10px;background:#f3f4f6;color:#374151;border:1px solid #e5e7eb;padding:1px 8px;margin-right:4px;border-radius:9999px">#${escapeHtml(t)}</span>`,
              )
              .join("")}</div>`
          : "";
      // Image (Phase 4). Inlined as a data URI so the exported PDF/
      // HTML is fully offline-portable. ``max-width: 100%`` keeps
      // wide renders from busting the column; the rounded corner +
      // soft border match the in-app section image style.
      const imgHtml = s.imageUrl
        ? `<img src="${s.imageUrl}" alt="${escapeHtml(s.title)}" style="display:block;max-width:100%;margin:8px 0 12px 0;border-radius:6px;border:1px solid #e5e7eb" />`
        : "";
      return `
  <section style="margin-bottom:32px;page-break-inside:avoid">
    <h1 style="font-size:20px;margin:0 0 4px 0;color:#111">${escapeHtml(s.title)}</h1>
    <p style="font-size:11px;color:#888;margin:0 0 8px 0;font-style:italic">${escapeHtml(date)}</p>
    ${tagsHtml}
    ${imgHtml}
    ${blocks}
  </section>`;
    })
    .join('\n  <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0" />\n');

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>${escapeHtml(notebookTitle)}</title>
</head>
<body style="font-family:'Inter','Helvetica Neue',Arial,sans-serif;color:#1f2937;line-height:1.55;font-size:13px;padding:32px;max-width:680px;margin:0 auto;background:#fff">
  <header style="border-bottom:2px solid #111;padding-bottom:8px;margin-bottom:24px">
    <h1 style="font-size:24px;margin:0;color:#111">${escapeHtml(notebookTitle)}</h1>
    <p style="font-size:11px;color:#666;margin:4px 0 0 0">Exported from KATHA AI · ${escapeHtml(formatHumanDate(new Date().toISOString()))}</p>
  </header>
${sectionHtml}
</body>
</html>`;
}

/** Slugify a string for use in filenames. Strips diacritics, replaces
 *  non-alphanumerics with hyphens, collapses runs, trims edges. */
export function slugifyFilename(input: string, maxLen = 60): string {
  const stripped = input
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "") // strip combining diacritics
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return (stripped || "notes").slice(0, maxLen);
}
