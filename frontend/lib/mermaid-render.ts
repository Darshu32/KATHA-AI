"use client";

// Single source of truth for Mermaid rendering. Mermaid is browser-only and
// heavy, so it's imported lazily and initialised once. Two consumers share it:
//   • <MermaidDiagram> renders the SVG inline (chat message + sidebar note).
//   • the PDF export rasterises the SVG to a PNG the server can embed, since
//     reportlab has no browser to run mermaid itself.

let _seq = 0;
let _inited = false;

async function getMermaid() {
  const mermaid = (await import("mermaid")).default;
  if (!_inited) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "loose",
      theme: "neutral",
      // Concrete web-safe stack (not "inherit"): the rasteriser loads the SVG
      // in an isolated <img> context with no page CSS, so labels must carry a
      // font that always resolves.
      fontFamily: "Arial, Helvetica, sans-serif",
      // SVG <text> labels rather than HTML <foreignObject> — the latter cannot
      // be drawn to a <canvas>, which would break PNG rasterisation.
      htmlLabels: false,
      flowchart: { htmlLabels: false },
    });
    _inited = true;
  }
  return mermaid;
}

/** Render a Mermaid chart to an inline SVG string. Throws on parse error. */
export async function renderMermaidSvg(chart: string): Promise<string> {
  const mermaid = await getMermaid();
  const id = `mmd-${(_seq += 1)}`;
  const { svg } = await mermaid.render(id, chart.trim());
  return svg;
}

/**
 * Rasterise a Mermaid chart to a PNG data URI (for embedding in the
 * server-rendered note PDF). Rendered at 2× for crispness. Returns ``null``
 * on any failure so callers degrade gracefully (fence/text fallback).
 */
export async function mermaidToPng(chart: string, scale = 2): Promise<string | null> {
  try {
    const svg = await renderMermaidSvg(chart);
    return await svgToPng(svg, scale);
  } catch {
    return null;
  }
}

/** Pull the intrinsic size out of the SVG and pin explicit width/height so it
 *  rasterises at a known size (mermaid emits width="100%" + a max-width style,
 *  which render as 0/undefined inside a bare <img>). */
function normaliseSvgSize(svgText: string): { w: number; h: number; svg: string } {
  let w = 0;
  let h = 0;

  const vb = svgText.match(/viewBox=["']([\d.\-\s,]+)["']/);
  if (vb) {
    const parts = vb[1].trim().split(/[\s,]+/).map(Number);
    if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
      w = parts[2];
      h = parts[3];
    }
  }
  const mw = svgText.match(/\bwidth=["']([\d.]+)(?:px)?["']/);
  const mh = svgText.match(/\bheight=["']([\d.]+)(?:px)?["']/);
  if (mw && parseFloat(mw[1]) > 0) w = parseFloat(mw[1]);
  if (mh && parseFloat(mh[1]) > 0) h = parseFloat(mh[1]);

  let svg = svgText
    .replace(/max-width:\s*[\d.]+px;?/g, "")
    .replace(/\bwidth=["'][^"']*["']/, `width="${w}"`)
    .replace(/\bheight=["'][^"']*["']/, `height="${h}"`);
  if (!/\bwidth=/.test(svg)) svg = svg.replace(/<svg/, `<svg width="${w}"`);
  if (!/\bheight=/.test(svg)) svg = svg.replace(/<svg/, `<svg height="${h}"`);

  return { w, h, svg };
}

function svgToPng(svgText: string, scale: number): Promise<string | null> {
  return new Promise((resolve) => {
    try {
      const { w, h, svg } = normaliseSvgSize(svgText);
      if (!w || !h) return resolve(null);

      const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.decoding = "async";
      img.onload = () => {
        try {
          const canvas = document.createElement("canvas");
          canvas.width = Math.round(w * scale);
          canvas.height = Math.round(h * scale);
          const ctx = canvas.getContext("2d");
          if (!ctx) {
            URL.revokeObjectURL(url);
            return resolve(null);
          }
          ctx.fillStyle = "#ffffff"; // flatten transparency → white page
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
          URL.revokeObjectURL(url);
          resolve(canvas.toDataURL("image/png"));
        } catch {
          URL.revokeObjectURL(url);
          resolve(null);
        }
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(null);
      };
      img.src = url;
    } catch {
      resolve(null);
    }
  });
}
