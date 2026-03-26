"use client";

import { useUIStore } from "../lib/store";

const THEMES = [
  { value: "modern", label: "Modern" },
  { value: "minimalist", label: "Minimalist" },
  { value: "traditional", label: "Traditional" },
  { value: "spanish", label: "Spanish" },
  { value: "italian", label: "Italian" },
  { value: "scandinavian", label: "Scandinavian" },
  { value: "industrial", label: "Industrial" },
  { value: "mid_century", label: "Mid-Century" },
  { value: "japanese", label: "Japanese" },
  { value: "bohemian", label: "Bohemian" },
  { value: "art_deco", label: "Art Deco" },
  { value: "rustic", label: "Rustic" },
];

interface ThemeSwitcherProps {
  onSwitch: (newStyle: string) => void;
  isLoading?: boolean;
}

export default function ThemeSwitcher({ onSwitch, isLoading }: ThemeSwitcherProps) {
  const currentTheme = useUIStore((s) => s.theme);
  const setTheme = useUIStore((s) => s.setTheme);

  const handleSwitch = (value: string) => {
    if (value === currentTheme || isLoading) return;
    setTheme(value);
    onSwitch(value);
  };

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-ink/70">Style Theme</h4>
      <div className="flex flex-wrap gap-2">
        {THEMES.map((t) => (
          <button
            key={t.value}
            onClick={() => handleSwitch(t.value)}
            disabled={isLoading}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              currentTheme === t.value
                ? "border-clay bg-clay text-white"
                : "border-black/10 bg-white/60 text-ink/70 hover:border-clay/30 hover:bg-clay/5"
            } disabled:opacity-50`}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}
