"use client";

import { ChangeEvent, FormEvent, useState } from "react";

import api, {
  ApiError,
  ApiErrorResponse,
  DesignGenerationRequest,
  DesignGenerationResponse,
} from "../lib/api-client";

const ROOM_TYPES = [
  "living room",
  "bedroom",
  "office",
  "kitchen",
  "dining room",
  "bathroom",
  "studio",
];

const THEMES = [
  "modern",
  "contemporary",
  "minimalist",
  "traditional",
  "rustic",
  "industrial",
  "scandinavian",
  "bohemian",
  "luxury",
  "coastal",
] as const;

const DIMENSIONS_PATTERN = /^\s*\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*(ft|feet|m|meter|meters)\s*$/i;

type DesignTheme = DesignGenerationRequest["theme"];
type FormState = {
  roomType: string;
  theme: DesignTheme;
  dimensions: string;
  requirements: string;
  budget: number | null;
};
type FormErrors = Partial<Record<keyof FormState, string>>;

interface PromptInputProps {
  onSuccess?: (response: DesignGenerationResponse) => void;
}

const INITIAL_STATE: FormState = {
  roomType: ROOM_TYPES[0],
  theme: THEMES[0],
  dimensions: "",
  requirements: "",
  budget: null,
};

function toLabel(value: string) {
  return value.replace(/\b\w/g, (char) => char.toUpperCase());
}

function validateForm(values: FormState): FormErrors {
  const errors: FormErrors = {};

  if (!values.roomType.trim()) {
    errors.roomType = "Room type is required.";
  }

  if (!values.theme.trim()) {
    errors.theme = "Theme is required.";
  }

  if (!values.dimensions.trim()) {
    errors.dimensions = "Dimensions are required.";
  } else if (!DIMENSIONS_PATTERN.test(values.dimensions)) {
    errors.dimensions = "Use a format like 10x12 ft.";
  }

  if (!values.requirements.trim()) {
    errors.requirements = "Requirements cannot be empty.";
  } else if (values.requirements.trim().length < 20) {
    errors.requirements = "Requirements must be at least 20 characters.";
  }

  if (values.budget !== null && Number.isNaN(values.budget)) {
    errors.budget = "Budget must be a valid number.";
  }

  return errors;
}

function extractApiError(error: unknown) {
  if (error instanceof ApiError) {
    const body = error.body as
      | ({
          detail?: ApiErrorResponse | Array<{ msg?: string }>;
        } & ApiErrorResponse)
      | null;

    const detail = body?.detail ?? body;

    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : null,
        )
        .filter(Boolean)
        .join(" ");
    }

    if (typeof detail === "string") {
      return detail;
    }

    if (detail && typeof detail === "object" && "message" in detail) {
      const detailedErrors =
        "details" in detail && Array.isArray(detail.details)
          ? detail.details
              .map((item) =>
                item && typeof item === "object" && "message" in item ? String(item.message) : null,
              )
              .filter(Boolean)
              .join(" ")
          : "";
      return detailedErrors ? `${String(detail.message)} ${detailedErrors}` : String(detail.message);
    }

    return `Request failed with status ${error.status}.`;
  }

  return error instanceof Error ? error.message : "Something went wrong while submitting the form.";
}

export default function PromptInput({ onSuccess }: PromptInputProps) {
  const [form, setForm] = useState<FormState>(INITIAL_STATE);
  const [errors, setErrors] = useState<FormErrors>({});
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [submissionResult, setSubmissionResult] = useState<DesignGenerationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const liveValidation = validateForm({
    ...form,
    roomType: form.roomType.trim(),
    theme: form.theme,
    dimensions: form.dimensions.trim(),
    requirements: form.requirements.trim(),
  });
  const isSubmitDisabled = isLoading || Object.keys(liveValidation).length > 0;

  const handleTextChange =
    (field: keyof Omit<FormState, "budget">) =>
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
      const nextValue = event.target.value;
      setForm((current) => ({ ...current, [field]: nextValue as FormState[typeof field] }));
      setErrors((current) => ({ ...current, [field]: undefined }));
      setSubmissionError(null);
    };

  const handleBudgetChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextValue = event.target.value;
      setForm((current) => ({
        ...current,
        budget: nextValue.trim() === "" ? null : Number(nextValue),
      }));
    setErrors((current) => ({ ...current, budget: undefined }));
    setSubmissionError(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedForm: FormState = {
      ...form,
      roomType: form.roomType.trim(),
      theme: form.theme,
      dimensions: form.dimensions.trim(),
      requirements: form.requirements.trim(),
    };

    const nextErrors = validateForm(trimmedForm);
    setErrors(nextErrors);
    setSubmissionResult(null);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setIsLoading(true);
    setSubmissionError(null);

    try {
      const response = await api.design.generate(trimmedForm);
      setSubmissionResult(response);
      setForm(INITIAL_STATE);
      onSuccess?.(response);
    } catch (error) {
      setSubmissionError(extractApiError(error));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="roomType" className="mb-1.5 block text-sm font-medium text-ink/70">
            Room type
          </label>
          <select
            id="roomType"
            value={form.roomType}
            onChange={handleTextChange("roomType")}
            className="w-full rounded-xl border border-black/10 bg-white/80 px-3 py-2.5 text-ink focus:border-clay/50 focus:outline-none focus:ring-2 focus:ring-clay/20"
            disabled={isLoading}
          >
            {ROOM_TYPES.map((roomType) => (
              <option key={roomType} value={roomType}>
                {toLabel(roomType)}
              </option>
            ))}
          </select>
          {errors.roomType ? <p className="mt-1 text-sm text-red-600">{errors.roomType}</p> : null}
        </div>

        <div>
          <label htmlFor="theme" className="mb-1.5 block text-sm font-medium text-ink/70">
            Theme
          </label>
          <select
            id="theme"
            value={form.theme}
            onChange={handleTextChange("theme")}
            className="w-full rounded-xl border border-black/10 bg-white/80 px-3 py-2.5 text-ink focus:border-clay/50 focus:outline-none focus:ring-2 focus:ring-clay/20"
            disabled={isLoading}
          >
            {THEMES.map((theme) => (
              <option key={theme} value={theme}>
                {toLabel(theme)}
              </option>
            ))}
          </select>
          {errors.theme ? <p className="mt-1 text-sm text-red-600">{errors.theme}</p> : null}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="dimensions" className="mb-1.5 block text-sm font-medium text-ink/70">
            Dimensions
          </label>
          <input
            id="dimensions"
            type="text"
            value={form.dimensions}
            onChange={handleTextChange("dimensions")}
            placeholder="15x20 ft"
            className="w-full rounded-xl border border-black/10 bg-white/80 px-4 py-2.5 text-ink placeholder:text-ink/40 focus:border-clay/50 focus:outline-none focus:ring-2 focus:ring-clay/20"
            disabled={isLoading}
            aria-describedby="dimensions-hint"
          />
          <p id="dimensions-hint" className="mt-1 text-xs text-ink/55">
            Enter dimensions as `length x width unit`, for example `10x12 ft`.
          </p>
          {errors.dimensions ? <p className="mt-1 text-sm text-red-600">{errors.dimensions}</p> : null}
        </div>

        <div>
          <label htmlFor="budget" className="mb-1.5 block text-sm font-medium text-ink/70">
            Budget (optional)
          </label>
          <input
            id="budget"
            type="number"
            min="0"
            step="0.01"
            value={form.budget ?? ""}
            onChange={handleBudgetChange}
            placeholder="5000"
            className="w-full rounded-xl border border-black/10 bg-white/80 px-4 py-2.5 text-ink placeholder:text-ink/40 focus:border-clay/50 focus:outline-none focus:ring-2 focus:ring-clay/20"
            disabled={isLoading}
          />
          {errors.budget ? <p className="mt-1 text-sm text-red-600">{errors.budget}</p> : null}
        </div>
      </div>

      <div>
        <label htmlFor="requirements" className="mb-1.5 block text-sm font-medium text-ink/70">
          Requirements
        </label>
        <textarea
          id="requirements"
          value={form.requirements}
          onChange={handleTextChange("requirements")}
          placeholder="Need a bright entertaining space with storage, a sectional sofa, soft lighting, and room for six guests."
          rows={5}
          className="w-full resize-none rounded-xl border border-black/10 bg-white/80 px-4 py-3 text-ink placeholder:text-ink/40 focus:border-clay/50 focus:outline-none focus:ring-2 focus:ring-clay/20"
          disabled={isLoading}
        />
        <p className="mt-1 text-xs text-ink/55">Minimum 20 characters.</p>
        {errors.requirements ? (
          <p className="mt-1 text-sm text-red-600">{errors.requirements}</p>
        ) : null}
      </div>

      {submissionError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {submissionError}
        </div>
      ) : null}

      {submissionResult ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {submissionResult.message}. Design ID: {submissionResult.designId}
        </div>
      ) : null}

      <button
        type="submit"
        disabled={isSubmitDisabled}
        className="w-full rounded-xl bg-ink px-6 py-3 font-medium text-white transition-colors hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? (
          <span className="flex items-center justify-center gap-2">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            Starting design generation...
          </span>
        ) : (
          "Submit Design Brief"
        )}
      </button>
    </form>
  );
}
