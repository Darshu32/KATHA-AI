"use client";

import { useRef, useCallback, useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import {
  ArrowUp,
  Paperclip,
  SlidersHorizontal,
  Wand2,
  Home,
  Building2,
  Trees,
  Grid3x3,
  ChevronDown,
  Sparkles,
} from "lucide-react";
import { useAuthStore, useImageGenStore } from "@/lib/store";

interface ImageEmptyHeroProps {
  onGenerate: () => void;
  disabled?: boolean;
}

const PRESETS = [
  { label: "Modern villa", icon: Home, prompt: "Modern 2-storey villa with double-height living room, travertine walls, a central courtyard and large cantilever over the entry." },
  { label: "Courtyard house", icon: Trees, prompt: "Tropical courtyard house, 3000 sqft, with verandahs, sloping roof and breeze-wall in handmade brick." },
  { label: "2BHK apartment", icon: Grid3x3, prompt: "Modern 2BHK apartment with open living-dining, utility balcony and compact pooja niche." },
  { label: "Mixed-use block", icon: Building2, prompt: "Mixed-use four-storey block with retail podium, stepped terraces and perforated GFRC screen." },
  { label: "Floor plan", icon: Grid3x3, prompt: "Floor plan, 1200 sqft, three bedrooms, north-facing, vastu-aligned with kitchen in south-east." },
];

function greetPart(): { hi: string; phrase: string } {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return { hi: "Good morning", phrase: "what shall we render?" };
  if (h >= 12 && h < 17) return { hi: "Good afternoon", phrase: "ready to draw something?" };
  if (h >= 17 && h < 21) return { hi: "Good evening", phrase: "one last render before dusk?" };
  return { hi: "Hello", phrase: "the canvas is waiting." };
}

export default function ImageEmptyHero({ onGenerate, disabled }: ImageEmptyHeroProps) {
  const user = useAuthStore((s) => s.user);
  const name = user?.displayName?.split(" ")[0] || "Architect";
  const greet = useMemo(greetPart, []);

  const { prompt, setPrompt, theme, drawingType, ratio, quality } = useImageGenStore();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 220) + "px";
  }, []);

  useEffect(() => { resize(); }, [prompt, resize]);

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (prompt.trim() && !disabled) onGenerate();
    }
  };

  return (
    <section
      className="flex-1 flex flex-col overflow-y-auto chat-scrollbar relative"
      style={{ backgroundColor: "var(--paper)", fontFamily: "var(--sans)" }}
    >
      <div className="relative flex-1 flex flex-col items-center justify-center px-6 pt-10 pb-10">
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="inline-flex items-center gap-2 pl-1 pr-3 py-1 rounded-full"
          style={{ border: "1px solid var(--rule)", backgroundColor: "var(--paper)" }}
        >
          <span
            className="px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wide uppercase"
            style={{ backgroundColor: "var(--ink)", color: "var(--paper)" }}
          >
            Studio
          </span>
          <span className="text-[12px]" style={{ color: "var(--ink-2)" }}>
            {theme} · {drawingType.replace(/-/g, " ")} · {ratio} · {quality}
          </span>
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.08 }}
          className="mt-6 text-left w-full"
          style={{
            maxWidth: 720,
            fontFamily: "var(--display)",
            fontSize: "clamp(34px, 3.6vw, 44px)",
            fontWeight: 700,
            lineHeight: 1.1,
            letterSpacing: "-0.025em",
            color: "var(--ink)",
          }}
        >
          Hello, {name}
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.18 }}
          className="mt-1 text-left w-full"
          style={{
            maxWidth: 720,
            fontFamily: "var(--display)",
            fontSize: "clamp(28px, 3.2vw, 40px)",
            fontWeight: 500,
            lineHeight: 1.15,
            color: "var(--ink-3)",
            letterSpacing: "-0.02em",
          }}
        >
          {greet.hi}, {greet.phrase}
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.28, ease: [0.22, 1, 0.36, 1] }}
          className="relative mt-8 w-full"
          style={{ maxWidth: 720 }}
        >
          <div
            className="relative rounded-[20px] bg-white"
            style={{
              border: "1px solid var(--rule)",
              boxShadow: "0 1px 2px rgba(17,17,16,0.03)",
            }}
          >
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKey}
              rows={1}
              disabled={disabled}
              placeholder="Modern 2BHK with open living area and a pooja niche…"
              className="w-full resize-none bg-transparent px-6 pt-5 pb-3 focus:outline-none"
              style={{ fontFamily: "var(--sans)", fontSize: 16.5, lineHeight: 1.55, color: "var(--ink)" }}
            />

            {prompt.length === 0 && (
              <span
                className="pointer-events-none absolute top-[22px] right-6 inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] tracking-widest"
                style={{ fontFamily: "var(--mono)", borderColor: "var(--rule)", color: "var(--ink-3)" }}
              >
                TAB
              </span>
            )}

            <div className="flex items-center justify-between px-4 pb-4">
              <div className="flex items-center gap-1">
                <HeroIconBtn label="Reference image"><Paperclip size={15} /></HeroIconBtn>
                <HeroIconBtn label="Advanced"><SlidersHorizontal size={15} /></HeroIconBtn>
                <div className="h-5 w-px mx-1.5" style={{ backgroundColor: "var(--rule)" }} />
                <button
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-[12px] transition-colors"
                  style={{ color: "var(--ink-2)" }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--paper-2)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <Wand2 size={13} />
                  Enhance
                  <ChevronDown size={12} className="opacity-60" />
                </button>
              </div>

              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={onGenerate}
                disabled={!prompt.trim() || disabled}
                className="inline-flex items-center gap-2 h-10 px-4 rounded-full transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                style={{
                  backgroundColor: prompt.trim() ? "var(--ink)" : "var(--paper-2)",
                  color: prompt.trim() ? "var(--paper)" : "var(--ink-3)",
                  fontFamily: "var(--sans)",
                }}
              >
                {disabled ? <Sparkles size={14} className="animate-pulse" /> : <ArrowUp size={17} strokeWidth={2.4} />}
                <span className="text-[13px] font-medium">{disabled ? "Drafting" : "Generate"}</span>
              </motion.button>
            </div>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.4 }}
          className="mt-5 flex flex-wrap gap-2 justify-center"
          style={{ maxWidth: 720 }}
        >
          {PRESETS.map((p) => {
            const Icon = p.icon;
            return (
              <button
                key={p.label}
                onClick={() => setPrompt(p.prompt)}
                className="group inline-flex items-center gap-1.5 pl-3 pr-3.5 py-2 rounded-full transition-all"
                style={{ border: "1px solid var(--rule)", backgroundColor: "rgba(255,255,255,0.6)", fontFamily: "var(--sans)" }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--ink)";
                  e.currentTarget.style.backgroundColor = "#fff";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--rule)";
                  e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.6)";
                }}
              >
                <Icon size={13} style={{ color: "var(--ink-3)" }} />
                <span className="text-[13px]" style={{ color: "var(--ink-2)", fontWeight: 500 }}>
                  {p.label}
                </span>
              </button>
            );
          })}
        </motion.div>

      </div>
    </section>
  );
}

function HeroIconBtn({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <button
      title={label}
      aria-label={label}
      className="w-9 h-9 rounded-full flex items-center justify-center transition-colors"
      style={{ color: "var(--ink-3)" }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = "var(--ink)";
        e.currentTarget.style.backgroundColor = "var(--paper-2)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = "var(--ink-3)";
        e.currentTarget.style.backgroundColor = "transparent";
      }}
    >
      {children}
    </button>
  );
}

