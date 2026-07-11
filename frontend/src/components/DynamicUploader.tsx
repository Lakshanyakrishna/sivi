"use client";

import { useCallback, useRef, useState } from "react";
import { Upload, FileImage, FileText, Box } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PipelineRoute } from "@/lib/api";

const ACCEPTED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".pdf", ".svg"];

interface DynamicUploaderProps {
  route: PipelineRoute;
  onFileSelected: (file: File) => void;
  disabled?: boolean;
}

const ROUTE_CONFIG: Record<
  PipelineRoute,
  { label: string; hint: string; icon: typeof Upload }
> = {
  real_object: {
    label: "Drop a photo here, or click to browse",
    hint: "PNG or JPG of a physical object",
    icon: FileImage,
  },
  flat_graphic: {
    label: "Drop a graphic here, or click to browse",
    hint: "PNG, JPG, PDF, or SVG — logos, text, icons",
    icon: FileText,
  },
  packaging_dieline: {
    label: "Drop PDF or SVG dieline here",
    hint: "PDF or SVG with cut & fold lines",
    icon: Box,
  },
};

function hasAcceptedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export default function DynamicUploader({
  route,
  onFileSelected,
  disabled,
}: DynamicUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const config = ROUTE_CONFIG[route];

  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file) return;
      if (!hasAcceptedExtension(file.name)) {
        setError(
          `Unsupported file type. Accepted: ${ACCEPTED_EXTENSIONS.join(", ")}`,
        );
        return;
      }
      setError(null);
      onFileSelected(file);
    },
    [onFileSelected],
  );

  const Icon = config.icon;

  return (
    <div className="flex flex-col items-center gap-6">
      <div
        role="button"
        tabIndex={0}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === "Enter" || e.key === " "))
            inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (!disabled) handleFile(e.dataTransfer.files?.[0]);
        }}
        aria-disabled={disabled}
        className={cn(
          "flex w-full max-w-lg cursor-pointer flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed p-14 text-center transition-all",
          disabled && "cursor-not-allowed opacity-50",
          isDragging
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-muted-foreground/50 hover:bg-muted/30",
        )}
      >
        <div
          className={cn(
            "flex size-14 items-center justify-center rounded-full transition-colors",
            isDragging
              ? "bg-primary/10 text-primary"
              : "bg-muted text-muted-foreground",
          )}
        >
          <Icon className="size-7" />
        </div>
        <div className="space-y-1">
          <p className="text-base font-medium">{config.label}</p>
          <p className="text-sm text-muted-foreground">{config.hint}</p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          disabled={disabled}
          className="hidden"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
