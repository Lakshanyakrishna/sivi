"use client";

import type { PipelineRoute } from "@/lib/api";

const OPTIONS: { value: PipelineRoute; label: string; description: string }[] = [
  {
    value: "real_object",
    label: "Real Object",
    description: "A photo of a physical item (chair, shoe, etc.)",
  },
  {
    value: "flat_graphic",
    label: "Flat Graphic",
    description: "A logo, text, or icon",
  },
  {
    value: "packaging_dieline",
    label: "Packaging Dieline",
    description: "A flat template with cuts and folds",
  },
];

interface RoutingSwitchProps {
  value: PipelineRoute | null;
  onChange: (route: PipelineRoute) => void;
  disabled?: boolean;
}

export default function RoutingSwitch({ value, onChange, disabled }: RoutingSwitchProps) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {OPTIONS.map((option) => {
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            disabled={disabled}
            onClick={() => onChange(option.value)}
            aria-pressed={selected}
            className={`rounded-lg border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              selected
                ? "border-blue-500 bg-blue-500/10"
                : "border-black/10 hover:border-black/30 dark:border-white/15 dark:hover:border-white/30"
            }`}
          >
            <p className="text-sm font-semibold">{option.label}</p>
            <p className="mt-1 text-xs opacity-60">{option.description}</p>
          </button>
        );
      })}
    </div>
  );
}
