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

// Mermaid diagram-type keywords — used to recognise an *untagged* ``` fence
// whose body is actually a diagram (the model doesn't always label it
// ```mermaid).
const MERMAID_KEYWORDS =
  /^(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|mindmap|timeline|gitGraph|quadrantChart|requirementDiagram)\b/;

/** Lift any mermaid fenced block out of the prose. Returns the cleaned prose
 *  (so the diagram source never renders as a raw code block in the note) plus
 *  the first diagram found, if any. */
function extractAndStripMermaid(md: string): { cleaned: string; diagram: string | null } {
  let found: string | null = null;
  const cleaned = md
    .replace(/```([a-zA-Z]*)\s*\n([\s\S]*?)```/g, (full, lang: string, body: string) => {
      const l = (lang || "").toLowerCase();
      const isMermaid = l === "mermaid" || (!l && MERMAID_KEYWORDS.test(body.trim()));
      if (isMermaid) {
        if (!found) found = body.trim();
        return "";
      }
      return full;
    })
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { cleaned, diagram: found };
}

export function parseDeepModeToNotes(
  content: string,
  messageId: string,
  conversationId: string,
  sourceTitle?: string,
  diagram?: string,
): NoteSection {
  const blocks: NoteBlock[] = [];

  // Pull the mermaid diagram out of the prose first: it's rendered as a real
  // diagram (note view) / embedded image (PDF), not dumped as source text.
  const { cleaned: body, diagram: inlineDiagram } = extractAndStripMermaid(content);
  const finalDiagram = (diagram && diagram.trim()) || inlineDiagram || undefined;

  // Split by ## or ### headings
  const sectionRegex = /^#{2,3}\s+(?:\d+[.)]\s*)?(.+)$/gm;
  const headings: { title: string; start: number; end: number }[] = [];
  let match: RegExpExecArray | null;

  while ((match = sectionRegex.exec(body)) !== null) {
    headings.push({ title: match[1].trim(), start: match.index, end: 0 });
  }

  // Set end positions
  for (let i = 0; i < headings.length; i++) {
    headings[i].end = i + 1 < headings.length ? headings[i + 1].start : body.length;
  }

  if (headings.length === 0) {
    // No headings found — dump everything as paragraphs
    const parsed = parseSectionContent(body);
    blocks.push(...(parsed.length ? parsed : [makeBlock("paragraph", body.slice(0, 500))]));
  } else {
    // Add any content before first heading
    const preamble = body.slice(0, headings[0].start).trim();
    if (preamble) {
      blocks.push(makeBlock("paragraph", preamble));
    }

    for (const heading of headings) {
      const sectionBody = body.slice(
        heading.start + body.slice(heading.start).indexOf("\n") + 1,
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

  // Title the note from the user's own question when we have it (predictable,
  // clean) — falling back to the first heading or the first 60 chars only when
  // no question was passed. This avoids titling a note with the model's prose
  // (e.g. "Here is a visual representation of an HVAC system…").
  const cleanSource = (sourceTitle ?? "").replace(/[#*\n]/g, "").trim();
  const sectionTitle =
    cleanSource ||
    (headings.length > 0
      ? headings[0].title.replace(/concept\s*(explanation)?/i, "").trim() || headings[0].title
      : body.slice(0, 60).replace(/[#*\n]/g, "").trim());

  return {
    id: crypto.randomUUID(),
    title: sectionTitle || "Notes",
    date: new Date().toISOString(),
    sourceMessageId: messageId,
    sourceConversationId: conversationId,
    blocks,
    // Auto-generated sections start untagged. Tag-by-default heuristics
    // (e.g. derive from conversation title) deliberately deferred —
    // suggestions tend to feel noisy until the user has built up
    // their own tag vocabulary.
    tags: [],
    // Image generation runs async after the section is created
    // (see chat-workspace-mvp1.tsx). Until that resolves, the field
    // is null and the UI hides the image slot.
    imageUrl: null,
    // Deep-mode diagram (from the backend's dedicated field, or lifted from
    // the prose above). Rendered live in the note; rasterised for the PDF.
    diagram: finalDiagram,
  };
}
