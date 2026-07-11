"use client";

import { useState } from "react";
import { generateMesh, resolveUrl, type Asset } from "@/lib/api";
import EngineAViewer from "./three/EngineAViewer";
import EngineBViewer from "./three/EngineBViewer";
import EngineCViewer from "./three/EngineCViewer";

interface MeshPanelProps {
  asset: Asset;
  onUpdated: (asset: Asset) => void;
}

const ENGINE_LABELS: Record<string, string> = {
  real_object: "Engine A — AI Mesh Generation",
  flat_graphic: "Engine B — Algorithmic Extrusion",
  packaging_dieline: "Engine C — Kinematic Folding",
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

export default function MeshPanel({ asset, onUpdated }: MeshPanelProps) {
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setIsGenerating(true);
    setError(null);
    try {
      const updated = await generateMesh(asset.id);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Mesh generation failed");
    } finally {
      setIsGenerating(false);
    }
  }

  const engineLabel = asset.route ? ENGINE_LABELS[asset.route] : null;
  const summaryEntries = asset.mesh_summary
    ? Object.entries(asset.mesh_summary).filter(([key]) => key !== "note")
    : [];
  const note =
    typeof asset.mesh_summary?.note === "string" ? (asset.mesh_summary.note as string) : null;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-black/10 p-4 dark:border-white/15">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">Phase 3 — {engineLabel}</p>
          {asset.mesh_status === "done" && <p className="text-xs opacity-60">Mesh generated</p>}
        </div>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={isGenerating}
          className="shrink-0 rounded-full bg-foreground px-4 py-2 text-xs font-medium text-background transition-colors hover:bg-[#383838] disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-[#ccc]"
        >
          {isGenerating
            ? "Generating…"
            : asset.mesh_status === "done"
              ? "Re-generate"
              : "Generate 3D mesh"}
        </button>
      </div>

      {error && (
        <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
          {error}
        </p>
      )}

      {asset.mesh_status === "error" && asset.mesh_error && !error && (
        <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
          {asset.mesh_error}
        </p>
      )}

      {asset.mesh_status === "done" && (
        <>
          {asset.route === "real_object" && asset.mesh_url && (
            <EngineAViewer glbUrl={resolveUrl(asset.mesh_url)} />
          )}
          {asset.route === "flat_graphic" && <EngineBViewer assetId={asset.id} />}
          {asset.route === "packaging_dieline" && <EngineCViewer assetId={asset.id} />}

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
