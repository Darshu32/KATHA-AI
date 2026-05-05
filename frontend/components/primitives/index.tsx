/* Shared primitives. Slimmed down for the editorial design language —
 * dropped: handwritten Annotation, draft-page-number, bracketed section
 * tags. Kept: simple labels, dividers, paper card, key-value rows,
 * dimension line (now used only on the design canvas). */

import type { ReactNode } from "react";

// SectionTag — small uppercase mono label for major UI sections.
// No brackets, no decoration; the type does the work.
export function SectionTag({ children }: { children: ReactNode }) {
  return <span className="section-tag">{children}</span>;
}

// MonoTag — same shape as SectionTag, with optional accent color.
export function MonoTag({
  children,
  color,
}: {
  children: ReactNode;
  color?: "ink" | "terracotta" | "brass" | "olive" | "mustard" | "brick";
}) {
  const colorClass = {
    ink: "text-ink-soft",
    terracotta: "text-terracotta",
    brass: "text-brass",
    olive: "text-olive",
    mustard: "text-mustard",
    brick: "text-brick",
  }[color ?? "ink"];
  return <span className={`mono-tag ${colorClass}`}>{children}</span>;
}

// Annotation — quiet marginalia (timestamps, "auto-generated" tags).
// Now mono italic, no terracotta accent unless surrounding context calls
// for it — the goal is restraint.
export function Annotation({ children }: { children: ReactNode }) {
  return <span className="annotation">{children}</span>;
}

// PaperCard — quiet surface with hairline border + minimal shadow.
export function PaperCard({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`paper-card ${className}`}>{children}</div>;
}

// BrassRule — warm horizontal divider for major sectioning.
export function BrassRule() {
  return <div className="brass-rule" />;
}

// BrassKV — key/value row (cost streams, spec summaries).
export function BrassKV({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="brass-kv">
      <span className="text-ink-soft">{k}</span>
      <span className="v tnum">{v}</span>
    </div>
  );
}

// DimensionLine — kept for use on the design canvas surface only.
// No longer used in chat or general UI.
export function DimensionLine({ label }: { label?: string }) {
  return (
    <div className="relative w-full flex items-center my-3">
      <div className="dim-line" />
      {label ? (
        <span className="absolute left-1/2 -translate-x-1/2 -top-3 px-2 bg-paper annotation">
          {label}
        </span>
      ) : null}
    </div>
  );
}
