"use client";

import { useEffect, useRef, useState } from "react";
import { renderMermaidSvg } from "@/lib/mermaid-render";

/**
 * Renders a Mermaid diagram string (from Deep-mode chat) to inline SVG.
 *
 * Rendering (lazy import + one-time init + config) lives in the shared
 * ``mermaid-render`` module so the on-screen SVG and the PDF-export raster
 * stay pixel-identical. If the text fails to parse we fall back to showing the
 * raw source rather than crashing the message.
 */
export default function MermaidDiagram({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const svg = await renderMermaidSvg(chart);
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
  }, [chart]);

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
