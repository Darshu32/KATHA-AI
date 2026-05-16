"use client";

/* BRD §1A — Project Brief panel.
 *
 * Lives at the top of the notes sidebar in the chat workspace. As the
 * user briefs a project conversationally in Deep mode, the backend
 * fills the 5-section schema (project_type / theme / space /
 * requirements / regulatory) and ships it down on every SSE ``done``
 * event. The chat store merges those snapshots into the active
 * conversation; this panel renders them.
 *
 * Visual treatment is intentionally different from regular notes:
 * it's a pinned card with status badges and a "Ready to design"
 * affordance, not a free-form note section. */

import { useMemo } from "react";
import { ArrowRight, CircleDot, CircleCheck, CircleDashed } from "lucide-react";
import type { ConvBrief, ConvBriefStatus, ConvBriefSectionStatus } from "@/lib/types";

const SECTION_ORDER: Array<{
  key: keyof ConvBriefStatus;
  label: string;
  hint: string;
}> = [
  { key: "project_type", label: "Project type", hint: "residential, office, hospitality…" },
  { key: "theme", label: "Theme", hint: "Pedestal · MCM · Contemporary · Modern · Custom" },
  { key: "space", label: "Space", hint: "length × width × height, site conditions" },
  { key: "requirements", label: "Requirements", hint: "functional needs, aesthetic, budget" },
  { key: "regulatory", label: "Regulatory", hint: "country, city, building codes, climate" },
];

interface Props {
  brief: ConvBrief | undefined;
  status: ConvBriefStatus | undefined;
  missing: string[] | undefined;
  onReadyToDesign?: () => void;
  readyDisabled?: boolean;
}

export default function ProjectBriefPanel({
  brief,
  status,
  missing,
  onReadyToDesign,
  readyDisabled,
}: Props) {
  // Hide the panel entirely until the first Deep response that
  // captures something. An empty brief shouldn't compete with the
  // regular notes for top-of-sidebar attention.
  const hasAnyContent = useMemo(
    () =>
      !!brief &&
      (["project_type", "theme", "space", "requirements", "regulatory"] as const).some(
        (k) => brief[k] && Object.keys(brief[k] as object).length > 0,
      ),
    [brief],
  );

  if (!hasAnyContent) return null;

  const allConfirmed =
    !!status &&
    SECTION_ORDER.every((s) => (status[s.key] ?? "pending") === "confirmed");

  return (
    <section className="px-4 py-3 border-b border-hairline bg-paper-soft/40">
      <header className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-soft">
            Project Brief
          </span>
          <span className="text-[10px] text-ink-mute font-mono">BRD §1A</span>
        </div>
      </header>

      <ol className="space-y-1.5">
        {SECTION_ORDER.map((s) => {
          const sectionStatus: ConvBriefSectionStatus =
            (status?.[s.key] ?? "pending") as ConvBriefSectionStatus;
          const sectionData = brief?.[s.key];
          return (
            <li key={s.key} className="flex items-start gap-2 text-[12px] leading-snug">
              <StatusIcon status={sectionStatus} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink-deep">{s.label}</span>
                  <StatusBadge status={sectionStatus} />
                </div>
                {sectionData && Object.keys(sectionData as object).length > 0 ? (
                  <SectionSummary data={sectionData as Record<string, unknown>} />
                ) : (
                  <p className="text-[11px] text-ink-mute italic">{s.hint}</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {missing && missing.length > 0 && (
        <p className="mt-2 text-[10px] text-ink-mute leading-snug">
          Still needed:{" "}
          <span className="font-mono">{missing.slice(0, 3).join(" · ")}</span>
          {missing.length > 3 && <span> · +{missing.length - 3} more</span>}
        </p>
      )}

      <button
        type="button"
        onClick={onReadyToDesign}
        disabled={!allConfirmed || readyDisabled || !onReadyToDesign}
        className={
          "mt-3 w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium transition-colors " +
          (allConfirmed && !readyDisabled
            ? "bg-ink-deep text-paper hover:bg-ink"
            : "bg-paper-deep text-ink-mute cursor-not-allowed")
        }
        title={
          allConfirmed
            ? "Send this brief to the design workspace"
            : "All 5 sections must be confirmed first"
        }
      >
        {allConfirmed ? "Ready to design" : "Brief in progress…"}
        {allConfirmed && <ArrowRight size={12} />}
      </button>
    </section>
  );
}

function StatusIcon({ status }: { status: ConvBriefSectionStatus }) {
  const common = "shrink-0 mt-0.5";
  if (status === "confirmed")
    return <CircleCheck size={14} className={`${common} text-emerald-600`} aria-label="confirmed" />;
  if (status === "partial")
    return <CircleDot size={14} className={`${common} text-amber-500`} aria-label="partial" />;
  return <CircleDashed size={14} className={`${common} text-ink-mute`} aria-label="pending" />;
}

function StatusBadge({ status }: { status: ConvBriefSectionStatus }) {
  const color =
    status === "confirmed"
      ? "bg-emerald-50 text-emerald-700"
      : status === "partial"
        ? "bg-amber-50 text-amber-700"
        : "bg-paper-deep text-ink-mute";
  return (
    <span
      className={`text-[9px] uppercase tracking-wider font-medium px-1.5 py-px rounded-full ${color}`}
    >
      {status}
    </span>
  );
}

/* Render a one-line summary of the captured fields for a section.
 * We don't pretty-print every nested object — for the sidebar we
 * just want a glance: "office · small" or "Mumbai, India". */
function SectionSummary({ data }: { data: Record<string, unknown> }) {
  const parts: string[] = [];
  // Pull a few likely keys in section-appropriate order.
  for (const key of ["type", "theme", "city", "country"]) {
    const v = data[key];
    if (typeof v === "string" && v.trim()) parts.push(v);
  }
  // Dimensions live one level deep.
  const dims = (data.dimensions as Record<string, unknown> | undefined) ?? undefined;
  if (dims && typeof dims === "object") {
    const l = dims.length;
    const w = dims.width;
    const u = dims.unit;
    if (l && w) parts.push(`${l}×${w}${u ? ` ${u}` : ""}`);
  }
  // Functional needs — show count.
  const needs = data.functional_needs;
  if (Array.isArray(needs) && needs.length > 0) {
    parts.push(`${needs.length} need${needs.length === 1 ? "" : "s"}`);
  }
  const budget = data.budget;
  if (typeof budget === "number" && budget > 0) {
    const currency = (data.currency as string) || "INR";
    parts.push(`${currency} ${budget.toLocaleString()}`);
  }
  // Sub-type / scale.
  for (const key of ["sub_type", "scale"]) {
    const v = data[key];
    if (typeof v === "string" && v.trim() && !parts.includes(v)) parts.push(v);
  }

  if (parts.length === 0) return null;
  return <p className="text-[11px] text-ink-soft truncate">{parts.join(" · ")}</p>;
}
