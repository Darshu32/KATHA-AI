"use client";

import { motion, AnimatePresence } from "framer-motion";
import { NotebookPen, PanelRightClose, Search, Trash2 } from "lucide-react";
import { useNotesStore } from "@/lib/store";
import NotebookView from "./notebook-view";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export default function NotesSidebar({ isOpen, onClose }: Props) {
  const { notebook, searchQuery, setSearchQuery } = useNotesStore();
  const sectionCount = notebook.sections.length;

  return (
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.aside
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 320, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="h-full bg-white border-l border-gray-200 flex flex-col overflow-hidden flex-shrink-0"
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-gray-100 flex-shrink-0">
            <div className="flex items-center justify-between mb-2.5">
              <div className="flex items-center gap-2">
                <NotebookPen size={16} className="text-gray-500" />
                <span className="text-sm font-semibold text-gray-800">Notes</span>
                {sectionCount > 0 && (
                  <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded-full">
                    {sectionCount}
                  </span>
                )}
              </div>
              <button
                onClick={onClose}
                className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
              >
                <PanelRightClose size={16} />
              </button>
            </div>

            {/* Search */}
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search notes..."
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-gray-50 border border-gray-200 rounded-lg text-gray-700 placeholder:text-gray-400 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors"
              />
            </div>
          </div>

          {/* Content */}
          <NotebookView />

          {/* Footer hint */}
          <div className="px-4 py-2 border-t border-gray-100 flex-shrink-0">
            <p className="text-[10px] text-gray-400 text-center">
              Deep mode conversations auto-generate notes
            </p>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
