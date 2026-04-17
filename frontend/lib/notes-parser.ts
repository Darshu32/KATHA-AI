import type { NoteBlock, NoteSection, NoteBlockType, CalloutVariant } from "./types";

function makeBlock(
  type: NoteBlockType,
  content: string,
  opts?: { calloutVariant?: CalloutVariant; indent?: number; children?: NoteBlock[] },
): NoteBlock {
  return {
    id: crypto.randomUUID(),
    type,
    content: content.trim(),
    indent: opts?.indent ?? 0,
    createdAt: new Date().toISOString(),
    ...(opts?.calloutVariant ? { calloutVariant: opts.calloutVariant } : {}),
    ...(opts?.children ? { children: opts.children, collapsed: true } : {}),
  };
}

function parseSectionContent(text: string): NoteBlock[] {
  const blocks: NoteBlock[] = [];
  const lines = text.split("\n");

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) continue;

    // Bullet list items
    if (/^[-*]\s+/.test(trimmed)) {
      const content = trimmed.replace(/^[-*]\s+/, "");
      blocks.push(makeBlock("bullet-list", content));
      continue;
    }

    // Numbered list items
    if (/^\d+[.)]\s+/.test(trimmed)) {
      const content = trimmed.replace(/^\d+[.)]\s+/, "");
      blocks.push(makeBlock("numbered-list", content));
      continue;
    }

    // Sub-headings (#### or bold lines)
    if (/^####\s+/.test(trimmed)) {
      blocks.push(makeBlock("heading-3", trimmed.replace(/^####\s+/, "")));
      continue;
    }

    // Bold-only lines become toggle blocks
    if (/^\*\*(.+?)\*\*\s*$/.test(trimmed)) {
      const title = trimmed.replace(/^\*\*(.+?)\*\*\s*$/, "$1");
      // Collect subsequent indented/bullet lines as children
      const children: NoteBlock[] = [];
      while (i + 1 < lines.length) {
        const next = lines[i + 1].trim();
        if (!next || /^#{2,4}\s/.test(next) || /^\*\*(.+?)\*\*\s*$/.test(next)) break;
        i++;
        if (/^[-*]\s+/.test(next)) {
          children.push(makeBlock("bullet-list", next.replace(/^[-*]\s+/, ""), { indent: 1 }));
        } else {
          children.push(makeBlock("paragraph", next, { indent: 1 }));
        }
      }
      blocks.push(makeBlock("toggle", title, { children: children.length ? children : undefined }));
      continue;
    }

    // Regular paragraph
    blocks.push(makeBlock("paragraph", trimmed));
  }

  return blocks;
}

function detectCalloutVariant(heading: string): CalloutVariant | null {
  const lower = heading.toLowerCase();
  if (lower.includes("mistake") || lower.includes("avoid") || lower.includes("don't") || lower.includes("pitfall")) {
    return "warning";
  }
  if (lower.includes("best practice") || lower.includes("standard") || lower.includes("recommendation") || lower.includes("tip")) {
    return "tip";
  }
  if (lower.includes("important") || lower.includes("critical") || lower.includes("note")) {
    return "important";
  }
  return null;
}

export function parseDeepModeToNotes(
  content: string,
  messageId: string,
  conversationId: string,
): NoteSection {
  const blocks: NoteBlock[] = [];

  // Split by ## or ### headings
  const sectionRegex = /^#{2,3}\s+(?:\d+[.)]\s*)?(.+)$/gm;
  const headings: { title: string; start: number; end: number }[] = [];
  let match: RegExpExecArray | null;

  while ((match = sectionRegex.exec(content)) !== null) {
    headings.push({ title: match[1].trim(), start: match.index, end: 0 });
  }

  // Set end positions
  for (let i = 0; i < headings.length; i++) {
    headings[i].end = i + 1 < headings.length ? headings[i + 1].start : content.length;
  }

  if (headings.length === 0) {
    // No headings found — dump everything as paragraphs
    const parsed = parseSectionContent(content);
    blocks.push(...(parsed.length ? parsed : [makeBlock("paragraph", content.slice(0, 500))]));
  } else {
    // Add any content before first heading
    const preamble = content.slice(0, headings[0].start).trim();
    if (preamble) {
      blocks.push(makeBlock("paragraph", preamble));
    }

    for (const heading of headings) {
      const sectionBody = content.slice(
        heading.start + content.slice(heading.start).indexOf("\n") + 1,
        heading.end,
      ).trim();

      const variant = detectCalloutVariant(heading.title);

      // Add heading block
      blocks.push(makeBlock("heading-2", heading.title));

      // If it's a warning/tip section, wrap the first meaningful content in a callout
      const sectionBlocks = parseSectionContent(sectionBody);

      if (variant && sectionBlocks.length > 0) {
        // First block becomes a callout
        const firstContent = sectionBlocks[0].content;
        blocks.push(makeBlock("callout", firstContent, { calloutVariant: variant }));
        blocks.push(...sectionBlocks.slice(1));
      } else {
        blocks.push(...sectionBlocks);
      }
    }
  }

  // Generate section title from the first heading or first 60 chars
  const sectionTitle =
    headings.length > 0
      ? headings[0].title.replace(/concept\s*(explanation)?/i, "").trim() || headings[0].title
      : content.slice(0, 60).replace(/[#*\n]/g, "").trim();

  return {
    id: crypto.randomUUID(),
    title: sectionTitle || "Notes",
    date: new Date().toISOString(),
    sourceMessageId: messageId,
    sourceConversationId: conversationId,
    blocks,
  };
}
