"use client";

import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import {
  ArrowUp,
  Paperclip,
  SlidersHorizontal,
  Hammer,
  Ruler,
  Sun,
  BookOpen,
  Layers,
  ChevronDown,
  MoveRight,
} from "lucide-react";
import { useAuthStore } from "@/lib/store";

interface ChatEmptyHeroProps {
  onSend: (text: string) => void;
  onSuggestionSelect: (prompt: string) => void;
  disabled?: boolean;
}

const SUGGESTIONS = [
  { label: "Facade study", icon: Layers, prompt: "Suggest modern villa facade design ideas with clean lines, large glass panels and natural materials." },
  { label: "Materials", icon: Hammer, prompt: "What are the best sustainable and eco-friendly building materials for residential architecture?" },
  { label: "Vastu layout", icon: Ruler, prompt: "Explain Vastu Shastra principles for a living-room layout with orientation and element placement." },
  { label: "Daylighting", icon: Sun, prompt: "Architectural strategies to maximise natural daylight in residential spaces?" },
  { label: "Precedents", icon: BookOpen, prompt: "Show me three built precedents of courtyard housing in tropical climates with drawings and why each works." },
];

function greetPart(): { hi: string; phrase: string } {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return { hi: "Good morning", phrase: "what shall we draft today?" };
  if (h >= 12 && h < 17) return { hi: "Good afternoon", phrase: "ready to draw something?" };
  if (h >= 17 && h < 21) return { hi: "Good evening", phrase: "still chasing the detail?" };
  return { hi: "Hello", phrase: "the studio is quiet — let's think." };
}

export default function ChatEmptyHero({ onSend, onSuggestionSelect, disabled }: ChatEmptyHeroProps) {
  const user = useAuthStore((s) => s.user);
  const name = user?.displayName?.split(" ")[0] || "Architect";
  const greet = useMemo(greetPart, []);
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 220) + "px";
  }, []);

  useEffect(() => { resize(); }, [value, resize]);

  const handleSend = () => {
    const t = value.trim();
    if (!t || disabled) return;
    onSend(t);
    setValue("");
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <section
      className="flex-1 flex flex-col overflow-y-auto chat-scrollbar relative"
      style={{ backgroundColor: "var(--paper)", fontFamily: "var(--sans)" }}
    >
      <div className="relative flex-1 flex flex-col items-center justify-center px-6 pt-10 pb-10">
        {/* badge */}
        <motion.a
          href="#"
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="inline-flex items-center gap-2 pl-1 pr-3 py-1 rounded-full border transition-colors"
          style={{ borderColor: "var(--rule)", backgroundColor: "var(--paper)" }}
        >
          <span
            className="px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wide uppercase"
            style={{ backgroundColor: "var(--paper-3)", color: "var(--ink-2)" }}
          >
            Beta
          </span>
          <span className="inline-flex items-center gap-1 text-[12px]" style={{ color: "var(--ink-2)" }}>
            Launch KATHA Computer <MoveRight size={12} className="opacity-60" />
          </span>
        </motion.a>

        {/* greeting */}
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

        {/* prompt card */}
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
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKey}
              rows={1}
              disabled={disabled}
              placeholder="Summarise the FSI implications of this plot boundary…"
              className="w-full resize-none bg-transparent px-6 pt-5 pb-3 focus:outline-none"
              style={{
                fontFamily: "var(--sans)",
                fontSize: 16.5,
                lineHeight: 1.55,
                color: "var(--ink)",
                fontWeight: 400,
              }}
            />

            {value.length === 0 && (
              <span
                className="pointer-events-none absolute top-[22px] right-6 inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] tracking-widest"
                style={{ fontFamily: "var(--mono)", borderColor: "var(--rule)", color: "var(--ink-3)" }}
              >
                TAB
              </span>
            )}

            <div className="flex items-center justify-between px-4 pb-4">
              <div className="flex items-center gap-1">
                <HeroIconBtn label="Attach"><Paperclip size={15} /></HeroIconBtn>
                <HeroIconBtn label="Tools"><SlidersHorizontal size={15} /></HeroIconBtn>
              </div>

              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={handleSend}
                disabled={!value.trim() || disabled}
                className="w-10 h-10 rounded-full flex items-center justify-center transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                style={{
                  backgroundColor: value.trim() ? "var(--ink)" : "var(--paper-2)",
                  color: value.trim() ? "var(--paper)" : "var(--ink-3)",
                }}
                aria-label="Send"
              >
                <ArrowUp size={17} strokeWidth={2.4} />
              </motion.button>
            </div>
          </div>
        </motion.div>

        {/* suggestions row */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.4 }}
          className="mt-5 flex flex-wrap gap-2 justify-center"
          style={{ maxWidth: 720 }}
        >
          {SUGGESTIONS.map((s) => {
            const Icon = s.icon;
            return (
              <button
                key={s.label}
                onClick={() => onSuggestionSelect(s.prompt)}
                className="group inline-flex items-center gap-1.5 pl-3 pr-3.5 py-2 rounded-full transition-all"
                style={{
                  border: "1px solid var(--rule)",
                  backgroundColor: "rgba(255,255,255,0.6)",
                  fontFamily: "var(--sans)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--ink)";
                  e.currentTarget.style.backgroundColor = "#fff";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--rule)";
                  e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.6)";
                }}
              >
                <Icon size={13} style={{ color: "var(--ink-3)" }} className="group-hover:!text-[var(--accent)]" />
                <span className="text-[13px]" style={{ color: "var(--ink-2)", fontWeight: 500 }}>
                  {s.label}
                </span>
              </button>
            );
          })}
          <button
            onClick={() => onSuggestionSelect("Show me more capabilities")}
            className="inline-flex items-center justify-center w-9 h-9 rounded-full transition-all"
            style={{ border: "1px solid var(--rule)", color: "var(--ink-3)" }}
            aria-label="More"
          >
            <ChevronDown size={14} />
          </button>
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

