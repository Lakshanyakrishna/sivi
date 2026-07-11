"use client";

import { useCallback, useRef, useState } from "react";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Download } from "lucide-react";
import { resolveUrl, type Asset } from "@/lib/api";
import type { MaterialStyle } from "@/lib/three-scene";
import EngineAViewer from "./three/EngineAViewer";
import EngineBViewer from "./three/EngineBViewer";
import EngineCViewer from "./three/EngineCViewer";

interface StudioProps {
  asset: Asset;
}

export default function Studio({ asset }: StudioProps) {
  const exportRef = useRef<(() => Promise<void>) | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const registerExport = useCallback((fn: () => Promise<void>) => {
    exportRef.current = fn;
  }, []);

  const [thickness, setThickness] = useState([30]);
  const [bevelThickness, setBevelThickness] = useState([6]);
  const [bevelSize, setBevelSize] = useState([6]);
  const [foldAngle, setFoldAngle] = useState([90]);
  const [materialStyle, setMaterialStyle] = useState<MaterialStyle>("matte");

  async function handleExport() {
    if (!exportRef.current) return;
    setIsExporting(true);
    try {
      await exportRef.current();
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      <div className="flex w-[30%] min-w-[260px] flex-col border-r border-border bg-muted/20 p-5">
        <div className="mb-5 space-y-1">
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Controls
          </h2>
          <p className="text-xs text-muted-foreground truncate">
            {asset.original_filename}
          </p>
        </div>

        <div className="flex-1 space-y-6">
          {asset.route === "flat_graphic" && (
            <div className="space-y-4">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Geometry
              </h3>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Extrusion Depth</Label>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {thickness[0].toFixed(1)}
                  </span>
                </div>
                <Slider
                  value={thickness}
                  onValueChange={setThickness}
                  min={1}
                  max={100}
                  step={0.5}
                />
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Bevel Depth</Label>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {bevelThickness[0].toFixed(1)}
                  </span>
                </div>
                <Slider
                  value={bevelThickness}
                  onValueChange={setBevelThickness}
                  min={0}
                  max={30}
                  step={0.5}
                />
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Bevel Size</Label>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {bevelSize[0].toFixed(1)}
                  </span>
                </div>
                <Slider
                  value={bevelSize}
                  onValueChange={setBevelSize}
                  min={0}
                  max={30}
                  step={0.5}
                />
              </div>
            </div>
          )}

          {asset.route === "packaging_dieline" && (
            <div className="space-y-4">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Folding
              </h3>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Fold Angle</Label>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {foldAngle[0].toFixed(0)}°
                  </span>
                </div>
                <Slider
                  value={foldAngle}
                  onValueChange={setFoldAngle}
                  min={0}
                  max={180}
                  step={1}
                />
              </div>
            </div>
          )}

          {asset.route === "real_object" && (
            <p className="text-xs text-muted-foreground">
              No geometry controls for real objects.
            </p>
          )}

          <div className="space-y-3 pt-2">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Material
            </h3>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={materialStyle}
              onValueChange={(value) => {
                if (value) setMaterialStyle(value as MaterialStyle);
              }}
              className="justify-start"
            >
              <ToggleGroupItem value="matte">Matte</ToggleGroupItem>
              <ToggleGroupItem value="glossy">Glossy</ToggleGroupItem>
              <ToggleGroupItem value="wireframe">Wireframe</ToggleGroupItem>
            </ToggleGroup>
          </div>
        </div>

        <div className="pt-4 border-t border-border">
          <Button
            className="w-full gap-2"
            size="lg"
            onClick={handleExport}
            disabled={isExporting}
          >
            <Download className="size-4" />
            {isExporting ? "Exporting…" : "Export .GLB"}
          </Button>
        </div>
      </div>

      {asset.route === "flat_graphic" || asset.route === "packaging_dieline" ? (
        <>
          <div className="flex w-[35%] min-w-[220px] flex-col border-r border-border">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <span className="text-xs font-medium text-muted-foreground">
                {asset.route === "flat_graphic" ? "2D Shape" : "Dieline (Cut / Fold)"}
              </span>
            </div>
            <div className="flex flex-1 items-center justify-center bg-muted/10 p-4">
              {asset.processed_preview_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={resolveUrl(asset.processed_preview_url)}
                  alt={asset.route === "flat_graphic" ? "Traced 2D contour" : "Classified dieline"}
                  className="max-h-full max-w-full rounded border border-border object-contain"
                />
              ) : (
                <span className="text-xs text-muted-foreground">No preview available</span>
              )}
            </div>
          </div>
          <div className="flex flex-1 flex-col">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <span className="text-xs font-medium text-muted-foreground">
                {asset.route === "flat_graphic" ? "3D Extrusion" : "3D Folded Box"}
              </span>
            </div>
            <div className="flex-1">
              <Viewport
                asset={asset}
                registerExport={registerExport}
                thickness={thickness[0]}
                bevelThickness={bevelThickness[0]}
                bevelSize={bevelSize[0]}
                foldAngle={foldAngle[0]}
                materialStyle={materialStyle}
              />
            </div>
          </div>
        </>
      ) : (
        <div className="flex flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-border px-5 py-3">
            <span className="text-xs font-medium text-muted-foreground">
              3D Viewport
            </span>
          </div>
          <div className="flex-1">
            <Viewport
              asset={asset}
              registerExport={registerExport}
              thickness={thickness[0]}
              bevelThickness={bevelThickness[0]}
              bevelSize={bevelSize[0]}
              foldAngle={foldAngle[0]}
              materialStyle={materialStyle}
            />
          </div>
        </div>
      )}
    </div>
  );
}

interface ViewportProps {
  asset: Asset;
  registerExport: (fn: () => Promise<void>) => void;
  thickness: number;
  bevelThickness: number;
  bevelSize: number;
  foldAngle: number;
  materialStyle: MaterialStyle;
}

function Viewport({
  asset,
  registerExport,
  thickness,
  bevelThickness,
  bevelSize,
  foldAngle,
  materialStyle,
}: ViewportProps) {
  if (asset.route === "real_object" && asset.mesh_url) {
    return (
      <EngineAViewer
        glbUrl={resolveUrl(asset.mesh_url)}
        hideControls
        materialStyle={materialStyle}
        registerExport={registerExport}
      />
    );
  }
  if (asset.route === "flat_graphic") {
    return (
      <EngineBViewer
        assetId={asset.id}
        hideControls
        externalValues={{ thickness, bevelThickness, bevelSize }}
        materialStyle={materialStyle}
        registerExport={registerExport}
      />
    );
  }
  if (asset.route === "packaging_dieline") {
    return (
      <EngineCViewer
        assetId={asset.id}
        hideControls
        externalFoldAngle={foldAngle}
        materialStyle={materialStyle}
        registerExport={registerExport}
      />
    );
  }
  return (
    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
      No 3D view available
    </div>
  );
}
