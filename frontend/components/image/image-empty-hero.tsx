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
  PenTool,
  Layers,
  Compass,
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
      style={{ backgroundColor: "var(--paper)", fontFamily: "var(--sans)", fontFeatureSettings: '"ss01", "cv11"' }}
    >
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div
          className="absolute inset-0"
          style={{
            backgroundImage:
              "linear-gradient(rgba(17,17,16,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(17,17,16,0.035) 1px, transparent 1px)",
            backgroundSize: "56px 56px",
            WebkitMaskImage: "radial-gradient(ellipse at 50% 30%, black 35%, transparent 85%)",
            maskImage: "radial-gradient(ellipse at 50% 30%, black 35%, transparent 85%)",
          }}
        />
      </div>

      <div className="relative flex-1 flex flex-col items-center px-6 pt-14 pb-10">
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="inline-flex items-center gap-2 pl-1 pr-3 py-1 rounded-full"
          style={{ border: "1px solid var(--rule)", backgroundColor: "var(--paper)" }}
        >
          <span
            className="px-2 py-0.5 rounded-full text-[10px] font-medium tracking-widest uppercase"
            style={{ fontFamily: "var(--mono)", backgroundColor: "var(--accent)", color: "#fff" }}
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
          className="mt-10 text-center inline-flex items-center justify-center gap-4"
          style={{
            fontFamily: "var(--display)",
            fontSize: "clamp(44px, 5.8vw, 72px)",
            fontWeight: 700,
            lineHeight: 0.98,
            letterSpacing: "-0.035em",
            color: "var(--ink)",
            fontOpticalSizing: "auto",
          }}
        >
          <span>
            {greet.hi},{" "}
            <span style={{ color: "var(--ink-2)", fontWeight: 500 }}>{name}</span>
          </span>
          <motion.span
            aria-hidden
            className="inline-flex items-center justify-center rounded-full"
            style={{
              width: "clamp(40px, 5.2vw, 56px)",
              height: "clamp(40px, 5.2vw, 56px)",
              backgroundColor: "var(--accent-soft)",
              color: "var(--accent-2)",
              border: "1px solid var(--rule)",
            }}
            animate={{ rotate: [-8, 6, -4, 0] }}
            transition={{ duration: 2.4, repeat: Infinity, repeatDelay: 5 }}
          >
            <PenTool size={20} strokeWidth={2} />
          </motion.span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.18 }}
          className="mt-4 text-center"
          style={{
            fontFamily: "var(--sans)",
            fontSize: "clamp(16px, 1.3vw, 19px)",
            fontWeight: 400,
            color: "var(--ink-3)",
            letterSpacing: "-0.005em",
          }}
        >
          {greet.phrase}
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.28, ease: [0.22, 1, 0.36, 1] }}
          className="relative mt-10 w-full"
          style={{ maxWidth: 720 }}
        >
          <div
            className="relative rounded-[24px] bg-white"
            style={{
              border: "1px solid var(--rule)",
              boxShadow:
                "0 1px 0 rgba(255,255,255,0.6) inset, 0 1px 2px rgba(17,17,16,0.04), 0 24px 40px -28px rgba(17,17,16,0.22)",
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

        <motion.aside
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.55 }}
          className="mt-auto pt-14 w-full"
          style={{ maxWidth: 720 }}
        >
          <div
            className="relative rounded-2xl overflow-hidden"
            style={{ border: "1px solid var(--rule)", backgroundColor: "rgba(255,255,255,0.7)", backdropFilter: "blur(2px)" }}
          >
            <div className="flex items-stretch">
              <div className="flex-1 px-6 py-5">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "var(--accent)" }} />
                  <span className="text-[10px] tracking-[0.22em] uppercase" style={{ fontFamily: "var(--mono)", color: "var(--ink-3)" }}>
                    Studio notes
                  </span>
                </div>
                <h3
                  className="leading-snug"
                  style={{ fontFamily: "var(--display)", fontSize: 17, fontWeight: 600, letterSpacing: "-0.015em", color: "var(--ink)" }}
                >
                  Outputs carry the current theme, drawing type, ratio and quality — change them in the right panel.
                </h3>
              </div>
              <div className="hidden md:flex items-center pr-5 gap-[10px]">
                <StudioTile index={0} icon={Home} />
                <StudioTile index={1} icon={Layers} />
                <StudioTile index={2} icon={Compass} />
              </div>
            </div>
          </div>
        </motion.aside>
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

function StudioTile({ index, icon: Icon }: { index: number; icon: typeof Home }) {
  return (
    <div
      className="w-[92px] h-[72px] rounded-lg relative overflow-hidden flex items-center justify-center"
      style={{
        transform: `rotate(${index === 0 ? -4 : index === 2 ? 4 : 0}deg)`,
        backgroundColor: index === 1 ? "var(--accent-soft)" : "var(--paper-2)",
        border: "1px solid var(--rule)",
      }}
    >
      <Icon size={22} strokeWidth={1.4} style={{ color: index === 1 ? "var(--accent-2)" : "var(--ink-2)" }} />
    </div>
  );
}
