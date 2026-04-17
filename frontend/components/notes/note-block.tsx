"use client";

import { memo, useRef, useCallback, useState } from "react";
import {
  ChevronRight,
  ChevronDown,
  Info,
  Lightbulb,
  AlertTriangle,
  AlertCircle,
  GripVertical,
  Trash2,
  Type,
} from "lucide-react";
import type { NoteBlock as NoteBlockType, NoteBlockType as BlockType, CalloutVariant } from "@/lib/types";
import { useNotesStore } from "@/lib/store";

interface Props {
  block: NoteBlockType;
  sectionId: string;
  index: number;
  onAddAfter: (afterBlockId: string) => void;
}

const CALLOUT_STYLES: Record<CalloutVariant, { bg: string; border: string; icon: typeof Info; iconColor: string }> = {
  info: { bg: "bg-blue-50", border: "border-blue-300", icon: Info, iconColor: "text-blue-500" },
  tip: { bg: "bg-green-50", border: "border-green-300", icon: Lightbulb, iconColor: "text-green-600" },
  warning: { bg: "bg-amber-50", border: "border-amber-300", icon: AlertTriangle, iconColor: "text-amber-500" },
  important: { bg: "bg-red-50", border: "border-red-300", icon: AlertCircle, iconColor: "text-red-500" },
};

const BLOCK_TYPE_OPTIONS: { value: BlockType; label: string }[] = [
  { value: "heading-2", label: "Heading" },
  { value: "paragraph", label: "Text" },
  { value: "bullet-list", label: "Bullet" },
  { value: "numbered-list", label: "Number" },
  { value: "callout", label: "Callout" },
  { value: "toggle", label: "Toggle" },
  { value: "divider", label: "Divider" },
];

function NoteBlock({ block, sectionId, index, onAddAfter }: Props) {
  const { activeBlockId, setActiveBlock, updateBlock, deleteBlock } = useNotesStore();
  const contentRef = useRef<HTMLDivElement>(null);
  const [showToolbar, setShowToolbar] = useState(false);
  const [showTypeMenu, setShowTypeMenu] = useState(false);
  const isActive = activeBlockId === block.id;

  const handleBlur = useCallback(() => {
    const text = contentRef.current?.innerText ?? "";
    if (text !== block.content) {
      updateBlock(sectionId, block.id, { content: text });
    }
    setActiveBlock(null);
  }, [block.id, block.content, sectionId, updateBlock, setActiveBlock]);

  const handleFocus = useCallback(() => {
    setActiveBlock(block.id);
  }, [block.id, setActiveBlock]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleBlur();
        onAddAfter(block.id);
      }
      if (e.key === "Backspace" && contentRef.current?.innerText === "") {
        e.preventDefault();
        deleteBlock(sectionId, block.id);
      }
      if (e.key === "Tab") {
        e.preventDefault();
        const newIndent = e.shiftKey
          ? Math.max(0, block.indent - 1)
          : Math.min(2, block.indent + 1);
        updateBlock(sectionId, block.id, { indent: newIndent });
      }
    },
    [block.id, block.indent, sectionId, deleteBlock, updateBlock, handleBlur, onAddAfter],
  );

  const handleTypeChange = (newType: BlockType) => {
    updateBlock(sectionId, block.id, { type: newType });
    setShowTypeMenu(false);
  };

  const indent = block.indent * 20;

  if (block.type === "divider") {
    return (
      <div
        className="py-2 group relative"
        style={{ paddingLeft: indent }}
        onMouseEnter={() => setShowToolbar(true)}
        onMouseLeave={() => setShowToolbar(false)}
      >
        <hr className="border-gray-200" />
      </div>
    );
  }

  // Callout block
  if (block.type === "callout") {
    const variant = block.calloutVariant ?? "info";
    const style = CALLOUT_STYLES[variant];
    const Icon = style.icon;
    return (
      <div
        className={`group relative flex gap-2 px-3 py-2 rounded-lg border-l-4 ${style.bg} ${style.border} my-1`}
        style={{ marginLeft: indent }}
        onMouseEnter={() => setShowToolbar(true)}
        onMouseLeave={() => { setShowToolbar(false); setShowTypeMenu(false); }}
      >
        <Icon size={14} className={`${style.iconColor} mt-0.5 flex-shrink-0`} />
        <div
          ref={contentRef}
          contentEditable
          suppressContentEditableWarning
          onBlur={handleBlur}
          onFocus={handleFocus}
          onKeyDown={handleKeyDown}
          className="flex-1 text-sm text-gray-700 outline-none leading-relaxed"
        >
          {block.content}
        </div>
        {showToolbar && <BlockToolbarInline onDelete={() => deleteBlock(sectionId, block.id)} />}
      </div>
    );
  }

  // Toggle block
  if (block.type === "toggle") {
    const isCollapsed = block.collapsed !== false;
    return (
      <div
        className="group relative my-0.5"
        style={{ paddingLeft: indent }}
        onMouseEnter={() => setShowToolbar(true)}
        onMouseLeave={() => { setShowToolbar(false); setShowTypeMenu(false); }}
      >
        <div className="flex items-start gap-1">
          <button
            onClick={() => updateBlock(sectionId, block.id, { collapsed: !isCollapsed })}
            className="p-0.5 mt-0.5 text-gray-400 hover:text-gray-600 rounded transition-transform"
          >
            {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          </button>
          <div
            ref={contentRef}
            contentEditable
            suppressContentEditableWarning
            onBlur={handleBlur}
            onFocus={handleFocus}
            onKeyDown={handleKeyDown}
            className="flex-1 text-sm font-medium text-gray-800 outline-none"
          >
            {block.content}
          </div>
        </div>
        {!isCollapsed && block.children && (
          <div className="ml-5 mt-1 pl-3 border-l-2 border-gray-200 space-y-0.5">
            {block.children.map((child, ci) => (
              <div key={child.id} className="text-sm text-gray-600">
                {child.type === "bullet-list" && <span className="text-gray-400 mr-1.5">-</span>}
                {child.content}
              </div>
            ))}
          </div>
        )}
        {showToolbar && <BlockToolbarInline onDelete={() => deleteBlock(sectionId, block.id)} />}
      </div>
    );
  }

  // Heading, paragraph, bullet, numbered
  const baseClasses: Record<string, string> = {
    "heading-1": "text-lg font-bold text-gray-900",
    "heading-2": "text-base font-semibold text-gray-800 mt-2",
    "heading-3": "text-sm font-semibold text-gray-700",
    paragraph: "text-sm text-gray-600 leading-relaxed",
    "bullet-list": "text-sm text-gray-600",
    "numbered-list": "text-sm text-gray-600",
  };

  return (
    <div
      className={`group relative flex items-start gap-1 my-0.5 ${isActive ? "bg-blue-50/50 rounded" : ""}`}
      style={{ paddingLeft: indent }}
      onMouseEnter={() => setShowToolbar(true)}
      onMouseLeave={() => { setShowToolbar(false); setShowTypeMenu(false); }}
    >
      {/* Prefix */}
      {block.type === "bullet-list" && (
        <span className="text-gray-400 mt-0.5 text-sm flex-shrink-0 w-4 text-center">-</span>
      )}
      {block.type === "numbered-list" && (
        <span className="text-gray-400 mt-0.5 text-sm flex-shrink-0 w-4 text-right mr-0.5">{index + 1}.</span>
      )}

      {/* Content */}
      <div
        ref={contentRef}
        contentEditable
        suppressContentEditableWarning
        onBlur={handleBlur}
        onFocus={handleFocus}
        onKeyDown={handleKeyDown}
        className={`flex-1 outline-none ${baseClasses[block.type] ?? "text-sm text-gray-600"}`}
      >
        {block.content}
      </div>

      {/* Inline toolbar */}
      {showToolbar && (
        <div className="absolute -left-6 top-0 flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => setShowTypeMenu(!showTypeMenu)}
            className="p-0.5 text-gray-300 hover:text-gray-500 rounded"
            title="Change type"
          >
            <Type size={11} />
          </button>
          <button
            onClick={() => deleteBlock(sectionId, block.id)}
            className="p-0.5 text-gray-300 hover:text-red-400 rounded"
            title="Delete"
          >
            <Trash2 size={11} />
          </button>
        </div>
      )}

      {/* Type menu dropdown */}
      {showTypeMenu && (
        <div className="absolute -left-6 top-6 z-20 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-28">
          {BLOCK_TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => handleTypeChange(opt.value)}
              className={`w-full text-left px-3 py-1 text-xs hover:bg-gray-50 ${
                block.type === opt.value ? "text-blue-600 font-medium" : "text-gray-600"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function BlockToolbarInline({ onDelete }: { onDelete: () => void }) {
  return (
    <button
      onClick={onDelete}
      className="absolute -right-1 top-0 p-0.5 text-gray-300 hover:text-red-400 rounded opacity-0 group-hover:opacity-100 transition-opacity"
      title="Delete block"
    >
      <Trash2 size={11} />
    </button>
  );
}

export default memo(NoteBlock);
