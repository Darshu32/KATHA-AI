"use client";

import { useEstimateStore } from "../lib/store";

interface LineItem {
  category: string;
  item_name: string;
  material: string;
  quantity: number;
  unit: string;
  unit_rate_low: number;
  unit_rate_high: number;
  total_low: number;
  total_high: number;
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}

const CATEGORY_COLORS: Record<string, string> = {
  wall: "bg-amber-100 text-amber-800",
  floor: "bg-emerald-100 text-emerald-800",
  ceiling: "bg-sky-100 text-sky-800",
  fixture: "bg-violet-100 text-violet-800",
  furniture: "bg-rose-100 text-rose-800",
};

export default function EstimatePanel() {
  const estimate = useEstimateStore((s) => s.estimate) as {
    line_items?: LineItem[];
    total_low?: number;
    total_high?: number;
    currency?: string;
    assumptions?: string[];
  } | null;

  if (!estimate || !estimate.line_items) {
    return (
      <div className="rounded-2xl border border-black/10 bg-white/60 p-6">
        <p className="text-sm text-ink/40">
          No estimate available. Generate a design first.
        </p>
      </div>
    );
  }

  const lineItems = estimate.line_items;
  const totalLow = estimate.total_low ?? 0;
  const totalHigh = estimate.total_high ?? 0;

  // Group by category
  const grouped = lineItems.reduce<Record<string, LineItem[]>>((acc, item) => {
    const cat = item.category;
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(item);
    return acc;
  }, {});

  return (
    <div className="space-y-4 rounded-2xl border border-black/10 bg-white/60 p-6">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg text-ink">Cost Estimate</h3>
        <span className="rounded-full bg-sage/20 px-3 py-1 text-xs font-medium text-sage">
          Approximate
        </span>
      </div>

      {/* Total range */}
      <div className="rounded-xl bg-ink p-4 text-white">
        <p className="text-xs uppercase tracking-wider text-white/60">
          Estimated range
        </p>
        <p className="mt-1 font-display text-2xl">
          {formatCurrency(totalLow)} — {formatCurrency(totalHigh)}
        </p>
      </div>

      {/* Line items by category */}
      <div className="space-y-3">
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            <div className="mb-2 flex items-center gap-2">
              <span
                className={`rounded-md px-2 py-0.5 text-xs font-semibold capitalize ${
                  CATEGORY_COLORS[category] ?? "bg-gray-100 text-gray-700"
                }`}
              >
                {category}
              </span>
            </div>
            <div className="space-y-1">
              {items.map((item, i) => (
                <div
                  key={`${category}-${i}`}
                  className="flex items-center justify-between rounded-lg bg-sand/50 px-3 py-2 text-sm"
                >
                  <div>
                    <p className="font-medium text-ink">{item.item_name}</p>
                    <p className="text-xs text-ink/50">
                      {item.quantity} {item.unit} &middot; {item.material}
                    </p>
                  </div>
                  <p className="text-right text-xs text-ink/70">
                    {formatCurrency(item.total_low)} —{" "}
                    {formatCurrency(item.total_high)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Assumptions */}
      {estimate.assumptions && estimate.assumptions.length > 0 && (
        <details className="text-xs text-ink/50">
          <summary className="cursor-pointer font-medium">Assumptions</summary>
          <ul className="mt-2 list-inside list-disc space-y-1">
            {estimate.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
