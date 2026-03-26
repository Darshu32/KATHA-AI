"use client";

import { useState } from "react";

const ROOM_TYPES = [
  "living_room",
  "bedroom",
  "kitchen",
  "bathroom",
  "dining_room",
  "office",
  "studio",
  "hallway",
  "balcony",
];

const STYLES = [
  "modern",
  "minimalist",
  "traditional",
  "spanish",
  "italian",
  "scandinavian",
  "industrial",
  "mid_century",
  "japanese",
  "bohemian",
  "art_deco",
  "rustic",
];

interface PromptInputProps {
  onSubmit: (data: {
    prompt: string;
    roomType: string;
    style: string;
  }) => void;
  isLoading?: boolean;
}

export default function PromptInput({ onSubmit, isLoading }: PromptInputProps) {
  const [prompt, setPrompt] = useState("");
  const [roomType, setRoomType] = useState("living_room");
  const [style, setStyle] = useState("modern");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isLoading) return;
    onSubmit({ prompt: prompt.trim(), roomType, style });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Prompt textarea */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-ink/70">
          Describe your design
        </label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Design a warm living room with natural stone walls, wooden beams, a large sofa facing a fireplace, and seating for six..."
          rows={4}
          className="w-full resize-none rounded-xl border border-black/10 bg-white/80 px-4 py-3 text-ink placeholder:text-ink/40 focus:border-clay/50 focus:outline-none focus:ring-2 focus:ring-clay/20"
          disabled={isLoading}
        />
      </div>

      {/* Room type + Style selectors */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-ink/70">
            Room type
          </label>
          <select
            value={roomType}
            onChange={(e) => setRoomType(e.target.value)}
            className="w-full rounded-xl border border-black/10 bg-white/80 px-3 py-2.5 text-ink focus:border-clay/50 focus:outline-none focus:ring-2 focus:ring-clay/20"
            disabled={isLoading}
          >
            {ROOM_TYPES.map((rt) => (
              <option key={rt} value={rt}>
                {rt.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-ink/70">
            Style / Theme
          </label>
          <select
            value={style}
            onChange={(e) => setStyle(e.target.value)}
            className="w-full rounded-xl border border-black/10 bg-white/80 px-3 py-2.5 text-ink focus:border-clay/50 focus:outline-none focus:ring-2 focus:ring-clay/20"
            disabled={isLoading}
          >
            {STYLES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={!prompt.trim() || isLoading}
        className="w-full rounded-xl bg-ink px-6 py-3 font-medium text-white transition-colors hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? (
          <span className="flex items-center justify-center gap-2">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            Generating design...
          </span>
        ) : (
          "Generate Design"
        )}
      </button>
    </form>
  );
}
