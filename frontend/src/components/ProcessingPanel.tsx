"use client";

import { useState } from "react";
import { processAsset, resolveUrl, type Asset } from "@/lib/api";

interface ProcessingPanelProps {
  asset: Asset;
  onUpdated: (asset: Asset) => void;
}

const ROUTE_LABELS: Record<string, string> = {
  real_object: "Background removal",
  flat_graphic: "Contour tracing",
  packaging_dieline: "Line extraction & classification",
};

function humanizeKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ProcessingPanel({ asset, onUpdated }: ProcessingPanelProps) {
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleProcess() {
    setIsProcessing(true);
    setError(null);
    try {
      const updated = await processAsset(asset.id);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Processing failed");
    } finally {
      setIsProcessing(false);
    }
  }

  const routeLabel = asset.route ? ROUTE_LABELS[asset.route] : null;
  const summaryEntries = asset.feature_summary
    ? Object.entries(asset.feature_summary).filter(([key]) => key !== "note")
    : [];
  const note =
    typeof asset.feature_summary?.note === "string" ? (asset.feature_summary.note as string) : null;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-black/10 p-4 dark:border-white/15">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">Phase 2 — {routeLabel}</p>
          {asset.processing_status === "done" && (
            <p className="text-xs opacity-60">Processed successfully</p>
          )}
        </div>
        <button
          type="button"
          onClick={handleProcess}
          disabled={isProcessing}
          className="shrink-0 rounded-full bg-foreground px-4 py-2 text-xs font-medium text-background transition-colors hover:bg-[#383838] disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-[#ccc]"
        >
          {isProcessing
            ? "Processing…"
            : asset.processing_status === "done"
              ? "Re-run"
              : "Run processing"}
        </button>
      </div>

      {error && (
        <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
          {error}
        </p>
      )}

      {asset.processing_status === "error" && asset.processing_error && !error && (
        <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
          {asset.processing_error}
        </p>
      )}

      {asset.processing_status === "done" && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-xs opacity-60">Original</p>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={resolveUrl(`/api/assets/${asset.id}/artwork.png`)}
                alt="Original upload"
                className="w-full rounded-lg border border-black/10 bg-neutral-100 dark:border-white/15 dark:bg-neutral-800"
              />
            </div>
            <div>
              <p className="mb-1 text-xs opacity-60">Processed</p>
              {asset.processed_preview_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={resolveUrl(asset.processed_preview_url)}
                  alt="Processed result"
                  className="w-full rounded-lg border border-black/10 bg-neutral-100 dark:border-white/15 dark:bg-neutral-800"
                />
              )}
            </div>
          </div>

          {summaryEntries.length > 0 && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
              {summaryEntries.map(([key, value]) => (
                <div key={key}>
                  <dt className="opacity-60">{humanizeKey(key)}</dt>
                  <dd>{formatValue(value)}</dd>
                </div>
              ))}
            </dl>
          )}

          {note && (
            <p className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-3 text-xs text-yellow-700 dark:text-yellow-400">
              {note}
            </p>
          )}
        </>
      )}
    </div>
  );
}
