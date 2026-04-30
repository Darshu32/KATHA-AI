"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import type { SuggestionChip } from "@/lib/types";

/**
 * Last-ditch fallback used when the API is unreachable AND the
 * server's own fallback didn't fire. Stage 3F made the chip catalog
 * DB-backed; in normal operation the backend always returns at least
 * one chip. We keep one entry here so the empty-hero never looks
 * broken offline.
 */
const FALLBACK_SUGGESTIONS: SuggestionChip[] = [
  {
    label: "Modern villa facade ideas",
    prompt:
      "Suggest modern villa facade design ideas with clean lines, large glass panels, and natural materials",
  },
];

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface SuggestionChipsProps {
  /**
   * Where the chip is being shown. Defaults to ``chat_empty_hero``.
   * Used as the ``context`` query param to the public suggestions
   * endpoint so different surfaces can show different chips.
   */
  context?: string;
  /** Caller can pre-supply chips (skips the fetch). */
  suggestions?: SuggestionChip[];
  onSelect: (prompt: string) => void;
}

interface SuggestionsApiResponse {
  suggestions: Array<{
    slug: string;
    label: string;
    prompt: string;
    weight: number;
    tags: string[];
  }>;
  context: string | null;
  count: number;
}

export default function SuggestionChips({
  context = "chat_empty_hero",
  suggestions: passedIn,
  onSelect,
}: SuggestionChipsProps) {
  const [chips, setChips] = useState<SuggestionChip[]>(
    passedIn ?? FALLBACK_SUGGESTIONS,
  );
  const [loaded, setLoaded] = useState<boolean>(passedIn !== undefined);

  useEffect(() => {
    if (passedIn !== undefined) return;

    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(
          `${API_BASE}/suggestions?context=${encodeURIComponent(context)}`,
          { credentials: "omit" },
        );
        if (!res.ok) {
          // Backend itself falls back to a built-in list, so a 5xx
          // here is genuinely unusual. Keep the offline fallback.
          if (!cancelled) setLoaded(true);
          return;
        }
        const data = (await res.json()) as SuggestionsApiResponse;
        if (cancelled) return;
        if (data?.suggestions?.length) {
          setChips(
            data.suggestions.map((s) => ({
              label: s.label,
              prompt: s.prompt,
            })),
          );
        }
        setLoaded(true);
      } catch {
        // Network error → keep fallback chips, don't block rendering.
        if (!cancelled) setLoaded(true);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [context, passedIn]);

  return (
    <div
      className="flex flex-wrap gap-2 justify-center"
      data-loaded={loaded ? "true" : "false"}
    >
      {chips.map((chip, i) => (
        <motion.button
          key={i}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={() => onSelect(chip.prompt)}
          className="border border-gray-200 rounded-full px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 hover:border-gray-300 hover:text-gray-800 transition-colors cursor-pointer"
        >
          {chip.label}
        </motion.button>
      ))}
    </div>
  );
}
