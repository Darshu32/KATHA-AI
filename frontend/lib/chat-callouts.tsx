/**
 * Inline callout processing for assistant chat replies.
 *
 * Two patterns get visually distinguished from prose:
 *
 *   1. **Data values** — `900mm`, `2.7 m`, `0.4 W/m²K`, `12 m²`,
 *      `45 lux`, `120 kg`, `±0.5 mm`. These are the numbers an
 *      architect's eye actually scans for. We render them with
 *      tabular figures + a hairline pencil-coloured underline.
 *
 *   2. **Code references** — `NBC §4.2.1`, `ECBC 4.3`, `IS 875`,
 *      `ISO 9001`. These are the citations an architect uses to
 *      defend a number to a reviewer. We render them as small
 *      pencil-on-pencil-bg tokens so they read as citation chips.
 *
 * The processor walks ReactMarkdown's rendered children, splits each
 * plain-text node by the union regex, and replaces matches with
 * `<span class="datum">` / `<span class="code-ref">` while preserving
 * everything else (formatting, links, etc.) untouched. This is purely
 * presentational — the underlying markdown stays clean.
 */

import { Children, isValidElement, type ReactNode } from "react";

// Unit suffixes the architect cares about. Order matters for matching:
// longer tokens like "W/m²K" must come before "m" so they don't lose
// their tail. We use a single-letter character class for the unit
// boundary so "12meters" doesn't match "12m".
const UNIT_RE =
  /([±]?\s*\d+(?:[.,]\d+)?)\s*(W\/m²K|m²|m³|mm|cm|m(?=[\s.,;:!?)\]}]|$)|°C|lux|kg|kN|MPa|Pa|hr|min|sec|%)/gi;

// Code reference patterns. Each prefix has its own regex to keep
// false positives down — we don't want random uppercase tokens picked
// up just because they look like a standard.
const CODE_RE =
  /\b(NBC|ECBC|IS|ISO|EN|ASTM|BIS|CPWD)(?:[-\s])?(?:Part\s+\d+\s+)?(?:§\s*)?(\d+(?:[.\-]\d+)*(?::\d+)?)/g;

/**
 * Process a string into an array of React nodes, wrapping each match
 * of UNIT_RE or CODE_RE in the appropriate `<span>`. Non-matching
 * substrings pass through as plain text. Stable across re-renders —
 * key by index since the slices are positional and short-lived.
 */
export function processProseText(text: string): ReactNode[] {
  if (!text) return [];

  // First sweep: collect all matches across both regexes into a single
  // ordered list of (start, end, type, payload). Run both regexes
  // independently then merge — overlap resolution prefers the earlier
  // match, then the longer one.
  type Match = {
    start: number;
    end: number;
    kind: "datum" | "code-ref";
    inner: string;
  };
  const matches: Match[] = [];

  UNIT_RE.lastIndex = 0;
  for (let m; (m = UNIT_RE.exec(text)); ) {
    matches.push({
      start: m.index,
      end: m.index + m[0].length,
      kind: "datum",
      inner: m[0].replace(/\s+/g, " ").trim(),
    });
  }

  CODE_RE.lastIndex = 0;
  for (let m; (m = CODE_RE.exec(text)); ) {
    matches.push({
      start: m.index,
      end: m.index + m[0].length,
      kind: "code-ref",
      inner: m[0].trim(),
    });
  }

  if (matches.length === 0) return [text];

  matches.sort((a, b) => a.start - b.start || b.end - a.end);

  // Resolve overlaps: prefer earlier-starting, then longer.
  const accepted: Match[] = [];
  let cursor = -1;
  for (const m of matches) {
    if (m.start >= cursor) {
      accepted.push(m);
      cursor = m.end;
    }
  }

  // Stitch the result: interleave plain text with span wrappers.
  const out: ReactNode[] = [];
  let pos = 0;
  for (let i = 0; i < accepted.length; i++) {
    const m = accepted[i];
    if (m.start > pos) {
      out.push(text.slice(pos, m.start));
    }
    out.push(
      <span key={`cn-${i}-${m.start}`} className={m.kind}>
        {m.inner}
      </span>,
    );
    pos = m.end;
  }
  if (pos < text.length) {
    out.push(text.slice(pos));
  }
  return out;
}

/**
 * Recursively process React children, applying `processProseText` to
 * any string node. Non-string nodes (links, code spans, emphasis,
 * etc.) pass through unchanged — their inner text is still walked, so
 * a `<strong>120 kg</strong>` still gets the data callout wrapping.
 *
 * Use this from a ReactMarkdown `components.p` override to surface
 * callouts inside every paragraph without losing markdown semantics.
 */
export function processChildren(children: ReactNode): ReactNode[] {
  const out: ReactNode[] = [];
  Children.forEach(children, (child, idx) => {
    if (typeof child === "string") {
      out.push(...processProseText(child));
    } else if (isValidElement(child)) {
      // Element node — recurse into its children, returning a new
      // element with the processed children.
      const props = child.props as { children?: ReactNode };
      const processed = processChildren(props.children);
      const elem = child as React.ReactElement<{ children?: ReactNode }>;
      out.push(
        <elem.type {...(elem.props as object)} key={`elem-${idx}`}>
          {processed}
        </elem.type>,
      );
    } else {
      out.push(child);
    }
  });
  return out;
}
