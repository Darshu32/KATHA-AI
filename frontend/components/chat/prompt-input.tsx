"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { ArrowUp, Paperclip, Mic, ImageIcon } from "lucide-react";

interface PromptInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function PromptInput({
  onSend,
  disabled = false,
  placeholder = "Ask about materials, planning, facades…",
}: PromptInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, []);

  useEffect(() => {
    resize();
  }, [value, resize]);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="px-4 pb-5 pt-3" style={{ backgroundColor: "var(--paper)" }}>
      <div className="mx-auto" style={{ maxWidth: 760 }}>
        <div
          className="relative rounded-[22px] bg-white"
          style={{
            border: "1px solid var(--rule)",
            boxShadow:
              "0 1px 0 rgba(255,255,255,0.6) inset, 0 1px 2px rgba(17,17,16,0.04), 0 12px 28px -20px rgba(17,17,16,0.2)",
          }}
        >
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className="w-full resize-none bg-transparent px-5 pt-4 pb-2 focus:outline-none disabled:opacity-60"
            style={{
              fontFamily: "var(--sans)",
              fontSize: 15,
              lineHeight: 1.55,
              color: "var(--ink)",
              letterSpacing: "-0.005em",
            }}
          />

          <div className="flex items-center justify-between px-3 pb-3">
            <div className="flex items-center gap-0.5">
              <IconBtn label="Attach"><Paperclip size={14} /></IconBtn>
              <IconBtn label="Image reference"><ImageIcon size={14} /></IconBtn>
              <IconBtn label="Voice"><Mic size={14} /></IconBtn>
            </div>

            <button
              onClick={handleSend}
              disabled={!value.trim() || disabled}
              className="w-8 h-8 rounded-full flex items-center justify-center transition-all disabled:opacity-30 disabled:cursor-not-allowed"
              style={{
                backgroundColor: value.trim() && !disabled ? "var(--ink)" : "var(--paper-2)",
                color: value.trim() && !disabled ? "var(--paper)" : "var(--ink-3)",
              }}
              aria-label="Send"
            >
              <ArrowUp size={15} strokeWidth={2.4} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function IconBtn({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <button
      title={label}
      aria-label={label}
      className="w-8 h-8 rounded-full flex items-center justify-center transition-colors"
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
