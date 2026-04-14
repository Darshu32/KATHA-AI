"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Send, Paperclip, Mic, ImageIcon } from "lucide-react";

interface PromptInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function PromptInput({
  onSend,
  disabled = false,
  placeholder = "Ask about architecture concepts, materials, planning, facade ideas...",
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
    <div className="border-t border-gray-100 bg-white px-4 py-4">
      <div className="mx-auto max-w-chat">
        <div className="relative">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className="w-full resize-none rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 pr-12 text-[0.938rem] text-gray-900 placeholder:text-gray-400 focus:border-gray-300 focus:bg-white focus:outline-none focus:ring-1 focus:ring-gray-200 transition-colors disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={!value.trim() || disabled}
            className="absolute right-2 bottom-2 w-8 h-8 flex items-center justify-center rounded-xl bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={15} />
          </button>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1 mt-2 px-1">
          <button
            className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
            title="Attach file"
          >
            <Paperclip size={16} />
          </button>
          <button
            className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
            title="Image reference"
          >
            <ImageIcon size={16} />
          </button>
          <button
            className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
            title="Voice input"
          >
            <Mic size={16} />
          </button>
          <span className="ml-auto text-xs text-gray-300">
            Shift+Enter for new line
          </span>
        </div>
      </div>
    </div>
  );
}
