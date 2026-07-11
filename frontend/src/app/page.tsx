"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import Header from "@/components/Header";
import DynamicUploader from "@/components/DynamicUploader";
import Studio from "@/components/Studio";
import {
  setAssetRoute,
  uploadAsset,
  processAsset,
  generateMesh,
  resolveUrl,
  type Asset,
  type PipelineRoute,
} from "@/lib/api";

const ROUTE_MAP: Record<string, PipelineRoute> = {
  real_object: "real_object",
  flat_graphic: "flat_graphic",
  packaging_dieline: "packaging_dieline",
};

// The Real Object pipeline (rembg/onnxruntime) needs more RAM than this
// deployment's backend host provides and can crash it — hidden here, not
// removed, so it comes back the moment the backend moves to a bigger plan.
const REAL_OBJECT_ENABLED = process.env.NEXT_PUBLIC_ENABLE_REAL_OBJECT !== "false";

export default function Home() {
  const [asset, setAsset] = useState<Asset | null>(null);
  const [route, setRoute] = useState<PipelineRoute>("flat_graphic");
  const [isUploading, setIsUploading] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isGeneratingMesh, setIsGeneratingMesh] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFileSelected(file: File) {
    setIsUploading(true);
    setError(null);
    try {
      const uploaded = await uploadAsset(file);
      const routed = await setAssetRoute(uploaded.id, route);
      setAsset(routed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }

  async function handleProcess() {
    if (!asset) return;
    setIsProcessing(true);
    setError(null);
    try {
      const updated = await processAsset(asset.id);
      setAsset(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Processing failed");
    } finally {
      setIsProcessing(false);
    }
  }

  async function handleGenerateMesh() {
    if (!asset) return;
    setIsGeneratingMesh(true);
    setError(null);
    try {
      const updated = await generateMesh(asset.id);
      setAsset(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Mesh generation failed");
    } finally {
      setIsGeneratingMesh(false);
    }
  }

  function reset() {
    setAsset(null);
    setError(null);
  }

  return (
    <div className="flex h-dvh flex-col">
      <Header />
      <AnimatePresence mode="wait">
        {!asset ? (
          <motion.div
            key="ingestion"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
            className="flex flex-1 flex-col items-center justify-center gap-8 px-6"
          >
            <div className="space-y-2 text-center">
              <h1 className="text-2xl font-semibold tracking-tight">
                2D to 3D Converter
              </h1>
              <p className="text-sm text-muted-foreground">
                Upload an image, graphic, or dieline to generate a 3D model
              </p>
            </div>

            <Tabs
              value={route}
              onValueChange={(v) => setRoute(v as PipelineRoute)}
            >
              <TabsList>
                {REAL_OBJECT_ENABLED && (
                  <TabsTrigger value="real_object">Real Object</TabsTrigger>
                )}
                <TabsTrigger value="flat_graphic">Flat Graphic</TabsTrigger>
                <TabsTrigger value="packaging_dieline">
                  Packaging Dieline
                </TabsTrigger>
              </TabsList>
            </Tabs>

            <DynamicUploader
              route={route}
              onFileSelected={handleFileSelected}
              disabled={isUploading}
            />

            {isUploading && (
              <p className="text-sm text-muted-foreground">Uploading…</p>
            )}

            {error && (
              <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {error}
              </p>
            )}
          </motion.div>
        ) : (
          <motion.div
            key="studio"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35, ease: "easeInOut" }}
            className="flex flex-1 flex-col"
          >
            {asset.mesh_status === "done" ? (
              <Studio asset={asset} />
            ) : (
              <div className="flex flex-1 overflow-hidden">
                <div className="flex w-[30%] min-w-[260px] flex-col border-r border-border bg-muted/20 p-5">
                  <div className="mb-5 space-y-1">
                    <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      Pipeline
                    </h2>
                    <p className="text-xs text-muted-foreground truncate">
                      {asset.original_filename}
                    </p>
                  </div>

                  <div className="flex-1 space-y-6">
                    {asset.processing_status !== "done" && (
                      <div className="space-y-3">
                        <p className="text-sm font-medium">Phase 2 — Processing</p>
                        {asset.route && (
                          <p className="text-xs text-muted-foreground">
                            {asset.route === "real_object" && "Background removal"}
                            {asset.route === "flat_graphic" && "Contour tracing"}
                            {asset.route === "packaging_dieline" && "Line extraction & classification"}
                          </p>
                        )}
                        {isProcessing && (
                          <p className="text-xs text-muted-foreground">Processing…</p>
                        )}
                        {asset.processing_status === "error" && asset.processing_error && (
                          <p className="text-xs text-destructive">{asset.processing_error}</p>
                        )}
                        <button
                          type="button"
                          onClick={handleProcess}
                          disabled={isProcessing}
                          className="rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                        >
                          {isProcessing ? "Processing…" : "Run Processing"}
                        </button>
                      </div>
                    )}

                    {asset.processing_status === "done" && (
                      <div className="space-y-3">
                        <p className="text-sm font-medium">Phase 3 — Mesh Generation</p>
                        <p className="text-xs text-muted-foreground">
                          {asset.route === "real_object" && "AI Mesh Generation"}
                          {asset.route === "flat_graphic" && "Algorithmic Extrusion"}
                          {asset.route === "packaging_dieline" && "Kinematic Folding"}
                        </p>
                        {isGeneratingMesh && (
                          <p className="text-xs text-muted-foreground">Generating…</p>
                        )}
                        {asset.mesh_status === "error" && asset.mesh_error && (
                          <p className="text-xs text-destructive">{asset.mesh_error}</p>
                        )}
                        <button
                          type="button"
                          onClick={handleGenerateMesh}
                          disabled={isGeneratingMesh}
                          className="rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                        >
                          {isGeneratingMesh ? "Generating…" : "Generate 3D Mesh"}
                        </button>
                      </div>
                    )}
                  </div>

                  <div className="pt-4 border-t border-border">
                    <button
                      type="button"
                      onClick={reset}
                      className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                    >
                      Upload another file
                    </button>
                  </div>
                </div>

                <div className="flex flex-1 flex-col">
                  <div className="flex items-center justify-between border-b border-border px-5 py-3">
                    <span className="text-xs font-medium text-muted-foreground">
                      Preview
                    </span>
                  </div>
                  <div className="flex flex-1 items-center justify-center p-6">
                    {asset.processing_status === "done" && asset.processed_preview_url ? (
                      <img
                        src={resolveUrl(asset.processed_preview_url)}
                        alt="Processed preview"
                        className="max-h-full max-w-full rounded-lg border border-border object-contain"
                      />
                    ) : (
                      <div className="flex flex-col items-center gap-3 text-center">
                        <div className="size-8 animate-spin rounded-full border-2 border-border border-t-primary" />
                        <p className="text-sm text-muted-foreground">
                          {asset.processing_status === "done"
                            ? "Ready to generate mesh"
                            : "Processing your file…"}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
