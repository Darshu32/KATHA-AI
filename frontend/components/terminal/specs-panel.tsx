"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";

import api from "@/lib/api-client";
import { useAuthStore, useDesignStore } from "@/lib/store";
import type { MaterialSpecRow, SpecBundle } from "@/lib/types";

type SubTab = "material" | "manufacturing" | "mep" | "cost";

function fmtRange(v: [number, number] | null | undefined): string {
  if (!v) return "—";
  return `${v[0]} – ${v[1]}`;
}

function flat(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.map(flat).join("; ");
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, val]) => `${k}: ${flat(val)}`)
      .join(", ");
  }
  return String(v);
}

export default function SpecsPanel() {
  const { activeGraph, activeProjectId } = useDesignStore();
  const token = useAuthStore((s) => s.token);

  const [bundle, setBundle] = useState<SpecBundle | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<SubTab>("material");

  const fetchBundle = async () => {
    if (!token) {
      setError("Sign in to fetch specifications.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.design.getSpecs(token, activeProjectId);
      setBundle(res.spec_bundle);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Spec request failed");
    } finally {
      setLoading(false);
    }
  };

  if (!activeGraph) {
    return (
      <div className="p-4 text-[11px]" style={{ color: "var(--ink-3)" }}>
        Generate a design to build spec sheets.
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" style={{ backgroundColor: "var(--paper)" }}>
      <div
        className="flex items-center justify-between px-3 py-2"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <div className="flex gap-0.5">
          {(["material", "manufacturing", "mep", "cost"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="px-2 py-1 text-[10px] uppercase tracking-wider rounded"
              style={{
                color: t === tab ? "var(--ink)" : "var(--ink-3)",
                backgroundColor: t === tab ? "var(--paper-deep, #ece5d8)" : "transparent",
                fontWeight: t === tab ? 700 : 500,
              }}
            >
              {t}
            </button>
          ))}
        </div>
        <button
          onClick={fetchBundle}
          disabled={loading}
          className="flex items-center gap-1 text-[10px] px-2 py-1 rounded"
          style={{ border: "1px solid var(--rule)", color: "var(--ink)" }}
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          {bundle ? "Refresh" : "Build"}
        </button>
      </div>

      {error && (
        <div
          className="px-3 py-2 text-[11px]"
          style={{ color: "#b14a2c", borderBottom: "1px solid var(--rule)" }}
        >
          {error}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-auto">
        {!bundle ? (
          <div className="p-4 text-[11px]" style={{ color: "var(--ink-3)" }}>
            Click Build to generate the spec bundle (material schedule, manufacturing notes, MEP sizing, cost).
          </div>
        ) : (
          <>
            {tab === "material" && <MaterialView bundle={bundle} />}
            {tab === "manufacturing" && <ManufacturingView bundle={bundle} />}
            {tab === "mep" && <MepView bundle={bundle} />}
            {tab === "cost" && <CostView bundle={bundle} />}
          </>
        )}
      </div>
    </div>
  );
}

function MaterialView({ bundle }: { bundle: SpecBundle }) {
  const sections: [string, MaterialSpecRow[]][] = [
    ["Primary Structure", bundle.material.primary_structure],
    ["Secondary", bundle.material.secondary_materials],
    ["Upholstery", bundle.material.upholstery],
    ["Hardware", bundle.material.hardware],
    ["Finishing", bundle.material.finishing],
  ];
  return (
    <div>
      {sections.map(([label, rows]) => (
        rows.length > 0 && (
          <section key={label}>
            <SectionHeader label={label} count={rows.length} />
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr style={{ backgroundColor: "var(--paper-deep, #ece5d8)", color: "var(--ink-3)" }}>
                    {["Name", "Grade", "Finish", "Colour", "Supplier", "Lead (wk)", "Cost INR"].map((h) => (
                      <th key={h} className="text-left px-3 py-1.5 text-[10px] uppercase tracking-wider font-semibold">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, idx) => (
                    <tr key={idx} style={{ borderBottom: "1px solid var(--rule)" }}>
                      <td className="px-3 py-1.5" style={{ color: "var(--ink)", fontWeight: 600 }}>{r.name}</td>
                      <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{r.grade}</td>
                      <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{r.finish}</td>
                      <td className="px-3 py-1.5 font-mono text-[10px]" style={{ color: "var(--ink-3)" }}>{r.color}</td>
                      <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{r.supplier}</td>
                      <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{fmtRange(r.lead_time_weeks)}</td>
                      <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{fmtRange(r.cost_inr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )
      ))}
    </div>
  );
}

function ManufacturingView({ bundle }: { bundle: SpecBundle }) {
  return (
    <div>
      {Object.entries(bundle.manufacturing).map(([trade, block]) => (
        <section key={trade}>
          <SectionHeader label={trade.replace(/_/g, " ")} count={Object.keys(block).length} />
          <dl className="px-3 py-2 text-[11px]">
            {Object.entries(block).map(([k, v]) => (
              <div key={k} className="flex gap-3 py-1" style={{ borderBottom: "1px dashed var(--rule)" }}>
                <dt className="min-w-[180px]" style={{ color: "var(--ink-3)" }}>{k.replace(/_/g, " ")}</dt>
                <dd style={{ color: "var(--ink)" }}>{flat(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}

function MepView({ bundle }: { bundle: SpecBundle }) {
  return (
    <div>
      {(["hvac", "electrical", "plumbing"] as const).map((sys) => (
        <section key={sys}>
          <SectionHeader label={sys.toUpperCase()} count={Object.keys(bundle.mep[sys] ?? {}).length} />
          <dl className="px-3 py-2 text-[11px]">
            {Object.entries(bundle.mep[sys] ?? {}).map(([k, v]) => (
              <div key={k} className="flex gap-3 py-1" style={{ borderBottom: "1px dashed var(--rule)" }}>
                <dt className="min-w-[180px]" style={{ color: "var(--ink-3)" }}>{k.replace(/_/g, " ")}</dt>
                <dd style={{ color: "var(--ink)" }}>{flat(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}

function CostView({ bundle }: { bundle: SpecBundle }) {
  const totals = bundle.cost.totals;
  return (
    <div>
      <SectionHeader label={`Totals (${bundle.cost.currency})`} count={bundle.cost.line_items.length} />
      <div className="px-3 py-2 text-[11px]" style={{ color: "var(--ink)" }}>
        Low: {totals.low ?? "—"} · Base: {totals.base ?? "—"} · High: {totals.high ?? "—"}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr style={{ backgroundColor: "var(--paper-deep, #ece5d8)", color: "var(--ink-3)" }}>
              {["Category", "Item", "Qty", "Unit", "Rate", "Low", "High"].map((h) => (
                <th key={h} className="text-left px-3 py-1.5 text-[10px] uppercase tracking-wider font-semibold">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bundle.cost.line_items.map((li, idx) => (
              <tr key={idx} style={{ borderBottom: "1px solid var(--rule)" }}>
                <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{String(li.category ?? "—")}</td>
                <td className="px-3 py-1.5" style={{ color: "var(--ink)", fontWeight: 600 }}>
                  {String(li.itemName ?? li.item_name ?? li.name ?? "—")}
                </td>
                <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{String(li.quantity ?? "—")}</td>
                <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{String(li.unit ?? "—")}</td>
                <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{flat(li.unitRate ?? li.unit_rate)}</td>
                <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{flat(li.totalLow ?? li.total_low)}</td>
                <td className="px-3 py-1.5" style={{ color: "var(--ink-3)" }}>{flat(li.totalHigh ?? li.total_high)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {bundle.cost.assumptions.length > 0 && (
        <div className="px-3 py-2 text-[10px]" style={{ color: "var(--ink-4)" }}>
          Assumptions: {bundle.cost.assumptions.join(" · ")}
        </div>
      )}
    </div>
  );
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div
      className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-semibold"
      style={{
        color: "var(--ink-3)",
        backgroundColor: "var(--paper-deep, #ece5d8)",
        borderBottom: "1px solid var(--rule)",
        borderTop: "1px solid var(--rule)",
      }}
    >
      {label} · {count}
    </div>
  );
}
