"use client";

import { useEffect, useId, useRef, useState } from "react";

/**
 * Renders a Mermaid diagram string (from Deep-mode chat) to inline SVG.
 *
 * Mermaid is browser-only and heavy, so it is imported lazily inside the effect
 * — never during SSR, and out of the initial bundle. The diagram text comes from
 * the model, so it is rendered with securityLevel "strict" (labels sanitised),
 * and if it fails to parse we fall back to showing the raw source rather than
 * crashing the message.
 */
export default function MermaidDiagram({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const rawId = useId().replace(/[^a-zA-Z0-9]/g, "");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "neutral",
          fontFamily: "inherit",
        });
        const { svg } = await mermaid.render(`mmd-${rawId}`, chart.trim());
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
          setFailed(false);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chart, rawId]);

  if (failed) {
    return (
      <pre className="bg-gray-900 text-gray-100 rounded-xl p-3 overflow-x-auto my-3 text-xs">
        {chart}
      </pre>
    );
  }

  return (
    <div className="my-3 rounded-xl border border-gray-200 bg-white p-3">
      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-gray-400">
        Diagram
      </div>
      <div
        ref={ref}
        className="flex justify-center overflow-x-auto [&_svg]:h-auto [&_svg]:max-w-full"
      />
    </div>
  );
}
