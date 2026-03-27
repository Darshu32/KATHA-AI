"use client";

import PromptInput from "../../../components/prompt-input";

export default function NewProjectPage() {
  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="font-display text-3xl text-ink">New Design Request</h1>
      <p className="mt-2 text-ink/60">
        Submit a structured design brief for validation before the generation pipeline starts.
      </p>

      <div className="mt-8 rounded-3xl border border-black/5 bg-white/70 p-6 shadow-sm">
        <PromptInput />
      </div>
    </main>
  );
}
