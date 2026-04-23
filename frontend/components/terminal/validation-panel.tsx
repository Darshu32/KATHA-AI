"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, AlertTriangle, Info, Lightbulb, RefreshCw, Sparkles } from "lucide-react";

import api from "@/lib/api-client";
import { useAuthStore, useDesignStore } from "@/lib/store";
import type {
  DesignConstraintEntry,
  KnowledgeValidationConstraint,
  RecommendationItem,
  RecommendationsConstraint,
  ValidationIssue,
  ValidationReport,
} from "@/lib/types";

function findConstraint<T extends DesignConstraintEntry>(
  graph: ReturnType<typeof useDesignStore.getState>["activeGraph"],
  type: string,
): T | null {
  if (!graph?.constraints) return null;
  return (graph.constraints as DesignConstraintEntry[]).find((c) => c?.type === type) as T | null;
}

function IssueRow({ issue, kind }: { issue: ValidationIssue; kind: "error" | "warning" | "suggestion" }) {
  const Icon = kind === "error" ? AlertCircle : kind === "warning" ? AlertTriangle : Info;
  const color =
    kind === "error" ? "#b14a2c" : kind === "warning" ? "#b88a2a" : "#3a6a7a";
  return (
    <div
      className="flex gap-2 px-3 py-2 text-[11px]"
      style={{ borderBottom: "1px solid var(--rule)" }}
    >
      <Icon size={14} color={color} style={{ flexShrink: 0, marginTop: 1 }} />
      <div className="min-w-0">
        <div style={{ color: "var(--ink)", fontWeight: 600 }}>{issue.code}</div>
        <div style={{ color: "var(--ink-3)" }} className="mt-0.5">{issue.message}</div>
        <div style={{ color: "var(--ink-4)" }} className="mt-0.5 font-mono text-[10px]">
          {issue.path}
        </div>
      </div>
    </div>
  );
}

function RecRow({ item }: { item: RecommendationItem }) {
  const severityColor =
    item.severity === "nudge" ? "#b14a2c" : item.severity === "tip" ? "#b88a2a" : "#3a6a7a";
  return (
    <div className="px-3 py-2" style={{ borderBottom: "1px solid var(--rule)" }}>
      <div className="flex items-start gap-2">
        <Lightbulb size={14} color={severityColor} style={{ flexShrink: 0, marginTop: 2 }} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="text-[11px] font-semibold" style={{ color: "var(--ink)" }}>
              {item.title}
            </span>
            <span
              className="text-[9px] uppercase tracking-wider"
              style={{ color: severityColor }}
            >
              {item.severity}
            </span>
            <span className="text-[9px] uppercase tracking-wider" style={{ color: "var(--ink-4)" }}>
              · {item.category}
            </span>
          </div>
          <div className="text-[11px] mt-0.5" style={{ color: "var(--ink-3)" }}>
            {item.message}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ValidationPanel() {
  const { activeGraph, activeProjectId } = useDesignStore();
  const token = useAuthStore((s) => s.token);

  // Seed from constraints that were attached at generation time.
  const seededValidation = useMemo(
    () => findConstraint<KnowledgeValidationConstraint>(activeGraph, "knowledge_validation"),
    [activeGraph],
  );
  const seededRecs = useMemo(
    () => findConstraint<RecommendationsConstraint>(activeGraph, "ai_recommendations"),
    [activeGraph],
  );

  const [report, setReport] = useState<ValidationReport | null>(
    seededValidation
      ? {
          ok: seededValidation.ok,
          summary: seededValidation.summary,
          errors: seededValidation.errors,
          warnings: seededValidation.warnings,
          suggestions: seededValidation.suggestions,
        }
      : null,
  );
  const [recs, setRecs] = useState<RecommendationItem[]>(seededRecs?.items ?? []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Refresh when the active graph changes (after a new generation).
  useEffect(() => {
    if (seededValidation) {
      setReport({
        ok: seededValidation.ok,
        summary: seededValidation.summary,
        errors: seededValidation.errors,
        warnings: seededValidation.warnings,
        suggestions: seededValidation.suggestions,
      });
    }
    if (seededRecs) setRecs(seededRecs.items);
  }, [seededValidation, seededRecs]);

  const runValidate = async () => {
    if (!token) {
      setError("Sign in to refresh validation from backend.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.design.validate(token, activeProjectId);
      setReport(res.validation);
      setRecs(res.recommendations);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation request failed");
    } finally {
      setLoading(false);
    }
  };

  if (!activeGraph) {
    return (
      <div className="p-4 text-[11px]" style={{ color: "var(--ink-3)" }}>
        Generate a design to see validation results.
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" style={{ backgroundColor: "var(--paper)" }}>
      <div
        className="flex items-center justify-between px-3 py-2"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <div className="text-[11px]" style={{ color: "var(--ink)" }}>
          {report ? (
            <>
              <span className="font-semibold">
                {report.ok ? "No code violations" : "Issues found"}
              </span>
              <span className="ml-2" style={{ color: "var(--ink-3)" }}>{report.summary}</span>
            </>
          ) : (
            <span style={{ color: "var(--ink-3)" }}>No validation yet</span>
          )}
        </div>
        <button
          onClick={runValidate}
          disabled={loading}
          className="flex items-center gap-1 text-[10px] px-2 py-1 rounded"
          style={{
            border: "1px solid var(--rule)",
            color: "var(--ink)",
            backgroundColor: loading ? "var(--rule)" : "transparent",
          }}
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          {loading ? "Running…" : "Re-run"}
        </button>
      </div>

      {error && (
        <div
          className="px-3 py-2 text-[11px]"
          style={{ color: "#b14a2c", borderBottom: "1px solid var(--rule)" }}
        >
          {error}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto">
        {report?.errors?.length ? (
          <Section label="Errors" count={report.errors.length}>
            {report.errors.map((i, idx) => <IssueRow key={`e-${idx}`} issue={i} kind="error" />)}
          </Section>
        ) : null}
        {report?.warnings?.length ? (
          <Section label="Warnings" count={report.warnings.length}>
            {report.warnings.map((i, idx) => <IssueRow key={`w-${idx}`} issue={i} kind="warning" />)}
          </Section>
        ) : null}
        {report?.suggestions?.length ? (
          <Section label="Suggestions" count={report.suggestions.length}>
            {report.suggestions.map((i, idx) => <IssueRow key={`s-${idx}`} issue={i} kind="suggestion" />)}
          </Section>
        ) : null}

        {recs.length > 0 && (
          <Section label="Recommendations" count={recs.length} accent>
            {recs.map((r) => <RecRow key={r.id} item={r} />)}
          </Section>
        )}

        {!report?.errors?.length && !report?.warnings?.length && !report?.suggestions?.length && !recs.length && (
          <div className="p-4 text-[11px]" style={{ color: "var(--ink-3)" }}>
            Everything looks good — no issues or suggestions.
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ label, count, accent, children }: { label: string; count: number; accent?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <div
        className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] uppercase tracking-wider"
        style={{
          color: accent ? "#b46a3a" : "var(--ink-3)",
          backgroundColor: "var(--paper-deep, #ece5d8)",
          borderBottom: "1px solid var(--rule)",
        }}
      >
        {accent ? <Sparkles size={11} /> : null}
        <span className="font-semibold">{label}</span>
        <span>· {count}</span>
      </div>
      {children}
    </div>
  );
}
