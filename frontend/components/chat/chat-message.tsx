"use client";

import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Bot,
  User,
  Sparkles,
  Play,
  BookOpen,
  ExternalLink,
  FileText,
  GraduationCap,
} from "lucide-react";
import type { Message, ChatMedia, ResearchPaper, ReferenceLink } from "@/lib/types";

interface ChatMessageProps {
  message: Message;
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}
    >
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center mt-1">
          <Bot size={16} className="text-gray-500" />
        </div>
      )}

      <div className={`max-w-[75%] ${isUser ? "order-first" : ""}`}>
        <div
          className={
            isUser
              ? "bg-slate-900 text-white rounded-2xl rounded-br-md px-4 py-3"
              : "bg-gray-50 border border-gray-100 text-gray-900 rounded-2xl rounded-bl-md px-4 py-3"
          }
        >
          {isUser ? (
            <p className="text-[0.938rem] leading-relaxed whitespace-pre-wrap">
              {message.content}
            </p>
          ) : (
            <div className="message-prose text-[0.938rem]">
              {message.isStreaming && !message.content ? (
                <div className="flex items-center gap-1.5 py-1">
                  <span className="typing-dot w-1.5 h-1.5 bg-gray-400 rounded-full" />
                  <span className="typing-dot w-1.5 h-1.5 bg-gray-400 rounded-full" />
                  <span className="typing-dot w-1.5 h-1.5 bg-gray-400 rounded-full" />
                </div>
              ) : (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    code: ({ className, children, ...props }) => {
                      const isBlock = className?.includes("language-");
                      if (isBlock) {
                        return (
                          <pre className="bg-gray-900 text-gray-100 rounded-xl p-4 overflow-x-auto my-3 text-sm">
                            <code className={className} {...props}>
                              {children}
                            </code>
                          </pre>
                        );
                      }
                      return (
                        <code
                          className="bg-gray-200/60 text-gray-800 px-1.5 py-0.5 rounded text-sm font-mono"
                          {...props}
                        >
                          {children}
                        </code>
                      );
                    },
                    pre: ({ children }) => <>{children}</>,
                  }}
                >
                  {message.content}
                </ReactMarkdown>
              )}
            </div>
          )}
        </div>

        {/* AI-Generated Image */}
        {!isUser && message.images && message.images.length > 0 && (
          <AIImageDisplay images={message.images} />
        )}

        {/* Video Embed — Quick Mode */}
        {!isUser && message.video && (
          <VideoEmbed video={message.video} />
        )}

        {/* YouTube References — Deep Mode */}
        {!isUser && message.youtubeLinks && message.youtubeLinks.length > 0 && (
          <YouTubeReferences videos={message.youtubeLinks} />
        )}

        {/* Research Papers — Deep Mode */}
        {!isUser && message.researchPapers && message.researchPapers.length > 0 && (
          <ResearchPapersSection papers={message.researchPapers} />
        )}

        {/* Reference Links — Deep Mode */}
        {!isUser && message.referenceLinks && message.referenceLinks.length > 0 && (
          <ReferenceLinksSection links={message.referenceLinks} />
        )}

        {/* Suggestion Chips */}
        {!isUser && !message.isStreaming && message.suggestions && message.suggestions.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-3 px-1">
            {message.suggestions.map((suggestion, i) => (
              <button
                key={i}
                onClick={() => {
                  window.dispatchEvent(
                    new CustomEvent("katha-suggestion-select", { detail: suggestion })
                  );
                }}
                className="text-xs bg-white border border-gray-200 text-gray-700 px-3 py-1.5 rounded-full hover:bg-gray-50 hover:border-gray-300 transition-colors cursor-pointer"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}

        {/* Mode indicator */}
        {!isUser && !message.isStreaming && message.mode && (
          <div className="mt-2 px-1">
            <span className="text-[10px] uppercase tracking-wider text-gray-400">
              {message.mode === "deep" ? "Deep Analysis" : "Quick Answer"}
            </span>
          </div>
        )}
      </div>

      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-slate-900 flex items-center justify-center mt-1">
          <User size={14} className="text-white" />
        </div>
      )}
    </motion.div>
  );
}

// ── AI-Generated Image ─────────────────────────────────────────────────────

function AIImageDisplay({ images }: { images: ChatMedia[] }) {
  return (
    <div className="mt-3">
      <div className="flex items-center gap-1.5 mb-2 px-1">
        <Sparkles size={12} className="text-amber-500" />
        <span className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">
          AI Generated Visualization
        </span>
      </div>
      {images.map((img, i) => (
        <a
          key={i}
          href={img.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block group"
        >
          <div className="w-full rounded-xl overflow-hidden border border-gray-200 bg-gray-100 relative">
            <img
              src={img.thumbnail || img.url}
              alt={img.title || "AI Architecture Visualization"}
              className="w-full h-auto max-h-80 object-cover group-hover:scale-[1.02] transition-transform duration-300"
              loading="lazy"
            />
            <div className="absolute top-3 right-3 bg-black/50 backdrop-blur-sm rounded-lg px-2 py-1 flex items-center gap-1">
              <Sparkles size={10} className="text-amber-400" />
              <span className="text-white text-[10px] font-medium uppercase">
                {img.source || "AI"}
              </span>
            </div>
          </div>
        </a>
      ))}
    </div>
  );
}

// ── Video Embed (Quick Mode) ───────────────────────────────────────────────

function VideoEmbed({ video }: { video: ChatMedia }) {
  if (video.type === "youtube" && video.video_id) {
    return (
      <div className="mt-3">
        <div className="flex items-center gap-1.5 mb-2 px-1">
          <Play size={12} className="text-red-500" />
          <span className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">
            Video Reference
          </span>
        </div>
        <div className="w-full rounded-xl overflow-hidden border border-gray-200 bg-black aspect-video">
          <iframe
            src={`https://www.youtube.com/embed/${video.video_id}`}
            title={video.title || "Architecture Video"}
            className="w-full h-full"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        </div>
        <a
          href={video.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 mt-1.5 px-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
        >
          <ExternalLink size={10} />
          <span>Watch on YouTube</span>
          {video.channel && <span className="text-gray-400">· {video.channel}</span>}
        </a>
      </div>
    );
  }

  // Sora or other video source
  if (video.url) {
    return (
      <div className="mt-3">
        <div className="flex items-center gap-1.5 mb-2 px-1">
          <Play size={12} className="text-blue-500" />
          <span className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">
            AI Generated Video
          </span>
        </div>
        <div className="w-full rounded-xl overflow-hidden border border-gray-200 bg-black aspect-video">
          <video
            src={video.url}
            controls
            autoPlay
            muted
            loop
            className="w-full h-full object-cover"
          />
        </div>
      </div>
    );
  }

  return null;
}

// ── YouTube References (Deep Mode) ─────────────────────────────────────────

function YouTubeReferences({ videos }: { videos: ChatMedia[] }) {
  return (
    <div className="mt-3">
      <div className="flex items-center gap-1.5 mb-2 px-1">
        <Play size={12} className="text-red-500" />
        <span className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">
          Related Tutorials & Lectures
        </span>
      </div>
      <div className="space-y-2">
        {videos.map((video, i) => (
          <a
            key={i}
            href={video.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex gap-3 p-2 rounded-lg border border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm transition-all group"
          >
            {video.thumbnail && (
              <div className="flex-shrink-0 w-32 h-20 rounded-md overflow-hidden bg-gray-100 relative">
                <img
                  src={video.thumbnail}
                  alt={video.title}
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
                <div className="absolute inset-0 bg-black/20 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                  <Play size={20} className="text-white" fill="white" />
                </div>
              </div>
            )}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 line-clamp-2 group-hover:text-blue-600 transition-colors">
                {video.title}
              </p>
              {video.channel && (
                <p className="text-xs text-gray-500 mt-1">{video.channel}</p>
              )}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

// ── Research Papers (Deep Mode) ────────────────────────────────────────────

function ResearchPapersSection({ papers }: { papers: ResearchPaper[] }) {
  return (
    <div className="mt-3">
      <div className="flex items-center gap-1.5 mb-2 px-1">
        <GraduationCap size={12} className="text-purple-500" />
        <span className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">
          Research Papers
        </span>
      </div>
      <div className="space-y-1.5">
        {papers.map((paper, i) => (
          <a
            key={i}
            href={paper.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-start gap-2 p-2 rounded-lg border border-gray-200 bg-white hover:border-purple-200 hover:bg-purple-50/30 transition-all group"
          >
            <BookOpen size={14} className="text-purple-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm text-gray-800 group-hover:text-purple-700 transition-colors line-clamp-2">
                {paper.title}
              </p>
              <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                {paper.authors && <span className="truncate max-w-[200px]">{paper.authors}</span>}
                {paper.year && <span>{paper.year}</span>}
                {paper.citations != null && paper.citations > 0 && (
                  <span className="bg-gray-100 px-1.5 py-0.5 rounded text-[10px]">
                    {paper.citations} citations
                  </span>
                )}
              </div>
            </div>
            <ExternalLink size={12} className="text-gray-400 flex-shrink-0 mt-1" />
          </a>
        ))}
      </div>
    </div>
  );
}

// ── Reference Links (Deep Mode) ────────────────────────────────────────────

function ReferenceLinksSection({ links }: { links: ReferenceLink[] }) {
  const validLinks = links.filter((l) => l.url && l.url.length > 0);
  if (validLinks.length === 0) return null;

  const typeColors: Record<string, string> = {
    standard: "bg-blue-50 text-blue-600 border-blue-100",
    article: "bg-green-50 text-green-600 border-green-100",
    documentation: "bg-orange-50 text-orange-600 border-orange-100",
    other: "bg-gray-50 text-gray-600 border-gray-100",
  };

  return (
    <div className="mt-3">
      <div className="flex items-center gap-1.5 mb-2 px-1">
        <FileText size={12} className="text-blue-500" />
        <span className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">
          Further Reading
        </span>
      </div>
      <div className="space-y-1.5">
        {validLinks.map((link, i) => (
          <a
            key={i}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 p-2 rounded-lg border border-gray-200 bg-white hover:border-gray-300 transition-all group"
          >
            <ExternalLink size={12} className="text-gray-400 flex-shrink-0" />
            <span className="text-sm text-gray-700 group-hover:text-blue-600 transition-colors flex-1 truncate">
              {link.title}
            </span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded border font-medium uppercase ${
                typeColors[link.type] || typeColors.other
              }`}
            >
              {link.type}
            </span>
          </a>
        ))}
      </div>
    </div>
  );
}
