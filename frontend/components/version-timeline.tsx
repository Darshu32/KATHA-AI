"use client";

interface Version {
  id: string;
  version: number;
  change_type: string;
  change_summary: string;
  created_at: string;
}

interface VersionTimelineProps {
  versions: Version[];
  currentVersion: number;
  onSelect: (version: number) => void;
}

const CHANGE_LABELS: Record<string, string> = {
  initial: "Initial design",
  prompt_edit: "Prompt edit",
  manual_edit: "Manual edit",
  theme_switch: "Theme switch",
  material_change: "Material change",
};

export default function VersionTimeline({
  versions,
  currentVersion,
  onSelect,
}: VersionTimelineProps) {
  if (!versions.length) {
    return (
      <p className="text-sm text-ink/40">No versions yet.</p>
    );
  }

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-ink/70">Version History</h4>
      <div className="space-y-1">
        {versions.map((v) => (
          <button
            key={v.id}
            onClick={() => onSelect(v.version)}
            className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
              v.version === currentVersion
                ? "border-clay/40 bg-clay/10"
                : "border-black/5 bg-white/40 hover:bg-white/70"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-ink">v{v.version}</span>
              <span className="text-ink/40">
                {new Date(v.created_at).toLocaleString()}
              </span>
            </div>
            <p className="mt-0.5 text-ink/60">
              {CHANGE_LABELS[v.change_type] ?? v.change_type}
              {v.change_summary ? ` — ${v.change_summary.slice(0, 60)}` : ""}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
