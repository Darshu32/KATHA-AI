"use client";

/**
 * NoteSectionImage — renders the auto-generated illustration that
 * accompanies a Deep Mode note section, with a hover-only remove
 * button.
 *
 * Why a dedicated component
 * -------------------------
 * Image rendering is one of those "tiny but easy to get wrong"
 * details: max-width handling, alt text, click-to-zoom hooks,
 * remove flow. Keeping it isolated makes future changes
 * (lightbox? carousel of variants? regenerate button?) cheap.
 *
 * Click-to-zoom
 * -------------
 * Clicking the image opens it in a new tab — the data URI works as
 * a URL, so the browser displays it full-size. No lightbox library
 * needed for v1; users who want a real lightbox can copy the image
 * out via right-click → save (which works because the data URI is
 * the image).
 */

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useNotesStore } from "@/lib/store";

interface Props {
  sectionId: string;
  imageUrl: string;
  alt: string;
}

export default function NoteSectionImage({ sectionId, imageUrl, alt }: Props) {
  const setSectionImage = useNotesStore((s) => s.setSectionImage);
  const [confirmRemove, setConfirmRemove] = useState(false);

  return (
    <div className="relative group/img mb-2 px-1">
      {/* Click to open full-size in a new tab — the data URI works
       *  as an href because browsers natively render image data URIs. */}
      <a
        href={imageUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="block"
        title="Open image in new tab"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imageUrl}
          alt={alt}
          className="w-full rounded-md border border-hairline hover:border-graphite transition-colors"
          // The image renderer reads the natural aspect from the
          // data URI bytes, so we don't pre-set width/height. A
          // very tall portrait would push the section down — fine,
          // matches user expectation.
        />
      </a>

      {/* Remove button — appears only on hover so the chrome stays
       *  quiet when the user is reading. Two-tap confirmation so a
       *  brushing finger / accidental click doesn't nuke a 200KB
       *  asset that took 10s to generate. */}
      <div className="absolute top-2 right-2 opacity-0 group-hover/img:opacity-100 transition-opacity">
        {confirmRemove ? (
          <div className="flex items-center gap-1 bg-paper/95 border border-hairline rounded-md px-1.5 py-1 shadow-card">
            <button
              onClick={() => {
                setSectionImage(sectionId, null);
                setConfirmRemove(false);
              }}
              className="text-[10px] text-pencil hover:text-pencil-soft font-medium"
            >
              Remove
            </button>
            <button
              onClick={() => setConfirmRemove(false)}
              className="text-[10px] text-ink-mute hover:text-ink"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmRemove(true)}
            className="p-1 bg-paper/90 border border-hairline text-ink-soft hover:text-pencil rounded-md shadow-card transition-colors"
            title="Remove image"
            aria-label="Remove image"
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>
    </div>
  );
}
