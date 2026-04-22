/**
 * Export the active 2D SVG floor plan or 3D WebGL canvas to PNG / JPEG / SVG / PDF.
 *
 * Strategy:
 * - 2D view: serialize the <svg>, draw it onto an <canvas> for raster outputs.
 * - 3D view: read the WebGL <canvas> directly via toDataURL.
 * - SVG: only meaningful for 2D — for 3D we wrap the PNG inside an <svg><image/></svg>.
 * - PDF: render the raster into a single-page minimal PDF (no external deps).
 */

export type ExportFormat = "PNG" | "JPEG" | "SVG" | "PDF";

const ACTIVE_VIEW_SELECTORS = {
  svg: "svg.max-w-full, .flex-1.min-h-0 svg",
  canvas: ".flex-1.min-h-0 canvas",
};

function findActiveView(): { kind: "svg"; el: SVGSVGElement } | { kind: "canvas"; el: HTMLCanvasElement } | null {
  const svg = document.querySelector<SVGSVGElement>(ACTIVE_VIEW_SELECTORS.svg);
  if (svg && svg.offsetParent !== null) return { kind: "svg", el: svg };
  const canvas = document.querySelector<HTMLCanvasElement>(ACTIVE_VIEW_SELECTORS.canvas);
  if (canvas) return { kind: "canvas", el: canvas };
  return null;
}

function downloadBlob(data: Blob | string, filename: string) {
  const url = typeof data === "string" ? data : URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  if (typeof data !== "string") setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function serializeSvg(svg: SVGSVGElement): string {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
  return new XMLSerializer().serializeToString(clone);
}

async function rasterizeSvg(svg: SVGSVGElement, mime: "image/png" | "image/jpeg", scale = 2): Promise<Blob> {
  const xml = serializeSvg(svg);
  const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  const img = new Image();
  await new Promise((resolve, reject) => {
    img.onload = () => resolve(null);
    img.onerror = reject;
    img.src = url;
  });
  const w = (svg.viewBox?.baseVal?.width || svg.clientWidth) * scale;
  const h = (svg.viewBox?.baseVal?.height || svg.clientHeight) * scale;
  const out = document.createElement("canvas");
  out.width = w;
  out.height = h;
  const ctx = out.getContext("2d")!;
  if (mime === "image/jpeg") {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);
  }
  ctx.drawImage(img, 0, 0, w, h);
  return await new Promise<Blob>((resolve) =>
    out.toBlob((b) => resolve(b!), mime, mime === "image/jpeg" ? 0.92 : undefined),
  );
}

function canvasToBlob(canvas: HTMLCanvasElement, mime: "image/png" | "image/jpeg"): Promise<Blob> {
  return new Promise<Blob>((resolve) => canvas.toBlob((b) => resolve(b!), mime, mime === "image/jpeg" ? 0.92 : undefined));
}

/**
 * Build a tiny single-page PDF that wraps a JPEG image. Avoids pulling jsPDF.
 * Spec: PDF 1.4, image XObject embedded as DCTDecode (JPEG raw bytes).
 */
async function buildSimplePdf(jpegBlob: Blob, widthPt: number, heightPt: number): Promise<Blob> {
  const jpegBytes = new Uint8Array(await jpegBlob.arrayBuffer());

  // Build the PDF as a string of objects, replacing image stream with raw bytes at the end.
  const enc = new TextEncoder();
  const objects: (string | Uint8Array)[] = [];
  const offsets: number[] = [];

  const pushObj = (s: string | Uint8Array) => {
    objects.push(s);
  };

  const headerStr = "%PDF-1.4\n%\xFF\xFF\xFF\xFF\n";
  const header = enc.encode(headerStr);

  // Object 1: catalog
  pushObj("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n");
  // Object 2: pages
  pushObj("2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n");
  // Object 3: page
  pushObj(
    `3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${widthPt} ${heightPt}] ` +
      `/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>\nendobj\n`,
  );
  // Object 4: image stream — header text + raw bytes + endstream
  const imgHeader = `4 0 obj\n<< /Type /XObject /Subtype /Image /Width ${Math.round(widthPt)} /Height ${Math.round(heightPt)} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpegBytes.length} >>\nstream\n`;
  const imgFooter = "\nendstream\nendobj\n";
  pushObj(imgHeader);
  pushObj(jpegBytes);
  pushObj(imgFooter);
  // Object 5: page content stream — draws image at full page
  const content = `q\n${widthPt} 0 0 ${heightPt} 0 0 cm\n/Im0 Do\nQ\n`;
  const stream5 = `5 0 obj\n<< /Length ${content.length} >>\nstream\n${content}endstream\nendobj\n`;
  pushObj(stream5);

  // Compute byte offsets and assemble.
  const chunks: Uint8Array[] = [header];
  let cursor = header.byteLength;
  for (let i = 0; i < objects.length; i++) {
    const part = objects[i];
    const bytes = typeof part === "string" ? enc.encode(part) : part;
    if (typeof part === "string" && /^\d+ 0 obj/.test(part)) {
      offsets.push(cursor);
    } else if (i > 0 && typeof objects[i - 1] === "string" && /^4 0 obj/.test(objects[i - 1] as string)) {
      // image bytes — already counted via header offset
    }
    chunks.push(bytes);
    cursor += bytes.byteLength;
  }

  // xref
  const xrefStart = cursor;
  let xref = `xref\n0 ${offsets.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) {
    xref += off.toString().padStart(10, "0") + " 00000 n \n";
  }
  const trailer = `trailer\n<< /Size ${offsets.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF\n`;
  chunks.push(enc.encode(xref + trailer));

  const total = chunks.reduce((a, c) => a + c.byteLength, 0);
  const out = new Uint8Array(total);
  let p = 0;
  for (const c of chunks) {
    out.set(c, p);
    p += c.byteLength;
  }
  return new Blob([out], { type: "application/pdf" });
}

export async function exportActiveView(format: ExportFormat, baseName = "katha-design"): Promise<{ ok: boolean; reason?: string }> {
  const view = findActiveView();
  if (!view) return { ok: false, reason: "No active design canvas to export." };

  const stamp = new Date().toISOString().slice(0, 16).replace(/[T:]/g, "-");
  const filename = `${baseName}-${stamp}`;

  try {
    if (format === "SVG") {
      if (view.kind === "svg") {
        const xml = serializeSvg(view.el);
        downloadBlob(new Blob([xml], { type: "image/svg+xml" }), `${filename}.svg`);
      } else {
        // Wrap the WebGL frame in an SVG image element (best-effort for 3D).
        const dataUrl = view.el.toDataURL("image/png");
        const w = view.el.width;
        const h = view.el.height;
        const xml = `<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><image href="${dataUrl}" width="${w}" height="${h}"/></svg>`;
        downloadBlob(new Blob([xml], { type: "image/svg+xml" }), `${filename}.svg`);
      }
      return { ok: true };
    }

    let blob: Blob;
    let widthPx: number;
    let heightPx: number;
    if (view.kind === "svg") {
      blob = await rasterizeSvg(view.el, format === "JPEG" ? "image/jpeg" : "image/png");
      widthPx = (view.el.viewBox?.baseVal?.width || view.el.clientWidth) * 2;
      heightPx = (view.el.viewBox?.baseVal?.height || view.el.clientHeight) * 2;
    } else {
      blob = await canvasToBlob(view.el, format === "JPEG" ? "image/jpeg" : "image/png");
      widthPx = view.el.width;
      heightPx = view.el.height;
    }

    if (format === "PDF") {
      // PDF needs JPEG bytes — convert if we currently have PNG.
      let jpegBlob = blob;
      if (blob.type !== "image/jpeg") {
        const img = new Image();
        const url = URL.createObjectURL(blob);
        await new Promise((res, rej) => {
          img.onload = res;
          img.onerror = rej;
          img.src = url;
        });
        const c = document.createElement("canvas");
        c.width = img.width;
        c.height = img.height;
        const ctx = c.getContext("2d")!;
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, c.width, c.height);
        ctx.drawImage(img, 0, 0);
        jpegBlob = await new Promise<Blob>((res) => c.toBlob((b) => res(b!), "image/jpeg", 0.9));
        URL.revokeObjectURL(url);
        widthPx = img.width;
        heightPx = img.height;
      }
      const pdf = await buildSimplePdf(jpegBlob, widthPx, heightPx);
      downloadBlob(pdf, `${filename}.pdf`);
    } else {
      downloadBlob(blob, `${filename}.${format.toLowerCase()}`);
    }

    return { ok: true };
  } catch (err) {
    return { ok: false, reason: err instanceof Error ? err.message : "Export failed" };
  }
}
