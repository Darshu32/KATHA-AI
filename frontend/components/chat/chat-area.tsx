"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Bot, ArrowDown } from "lucide-react";
import ChatMessage from "./chat-message";
import SuggestionChips from "./suggestion-chips";
import type { Message } from "@/lib/types";

interface ChatAreaProps {
  messages: Message[];
  isStreaming: boolean;
  onSuggestionSelect: (prompt: string) => void;
}

export default function ChatArea({
  messages,
  isStreaming,
  onSuggestionSelect,
}: ChatAreaProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const isNearBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }, []);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    if (isNearBottom()) {
      scrollToBottom();
    }
  }, [messages, isStreaming, isNearBottom, scrollToBottom]);

  const handleScroll = () => {
    setShowScrollButton(!isNearBottom());
  };

  // Empty state
  if (messages.length === 0 && !isStreaming) {
    return (
      <div className="flex-1 flex items-center justify-center px-4">
        <div className="text-center max-w-lg">
          <div className="w-14 h-14 rounded-2xl bg-gray-50 border border-gray-100 flex items-center justify-center mx-auto mb-6">
            <Bot size={24} className="text-gray-400" />
          </div>
          <h2 className="text-xl font-semibold text-gray-900 mb-2">
            Architecture Intelligence
          </h2>
          <p className="text-gray-500 text-sm mb-8 leading-relaxed">
            Ask about design concepts, building materials, Vastu principles,
            facade ideas, spatial planning, and more.
          </p>
          <SuggestionChips onSelect={onSuggestionSelect} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 relative">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="absolute inset-0 overflow-y-auto chat-scrollbar"
      >
        <div className="mx-auto max-w-chat py-8 px-4 space-y-6">
          {messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} />
          ))}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Scroll to bottom button */}
      {showScrollButton && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 w-8 h-8 bg-white border border-gray-200 rounded-full shadow-subtle flex items-center justify-center text-gray-500 hover:text-gray-700 hover:border-gray-300 transition-all"
        >
          <ArrowDown size={16} />
        </button>
      )}
    </div>
  );
}
