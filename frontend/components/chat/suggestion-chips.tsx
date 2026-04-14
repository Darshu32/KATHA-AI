"use client";

import { motion } from "framer-motion";
import type { SuggestionChip } from "@/lib/types";

const DEFAULT_SUGGESTIONS: SuggestionChip[] = [
  {
    label: "Modern villa facade ideas",
    prompt:
      "Suggest modern villa facade design ideas with clean lines, large glass panels, and natural materials",
  },
  {
    label: "Sustainable material options",
    prompt:
      "What are the best sustainable and eco-friendly building materials for residential architecture?",
  },
  {
    label: "Vastu living room layout",
    prompt:
      "Explain Vastu Shastra principles for designing a living room layout with proper orientation and element placement",
  },
  {
    label: "Natural lighting tips",
    prompt:
      "What are the best architectural strategies to maximize natural lighting in residential spaces?",
  },
];

interface SuggestionChipsProps {
  suggestions?: SuggestionChip[];
  onSelect: (prompt: string) => void;
}

export default function SuggestionChips({
  suggestions = DEFAULT_SUGGESTIONS,
  onSelect,
}: SuggestionChipsProps) {
  return (
    <div className="flex flex-wrap gap-2 justify-center">
      {suggestions.map((chip, i) => (
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
