"use client";

import { useCallback, useRef, useState } from "react";

const ACCEPTED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".pdf", ".svg"];

interface UploaderProps {
  onFileSelected: (file: File) => void;
  disabled?: boolean;
}

function hasAcceptedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export default function Uploader({ onFileSelected, disabled }: UploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file) return;
      if (!hasAcceptedExtension(file.name)) {
        setError(`Unsupported file type. Accepted: ${ACCEPTED_EXTENSIONS.join(", ")}`);
        return;
      }
      setError(null);
      onFileSelected(file);
    },
    [onFileSelected],
  );

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === "Enter" || e.key === " ")) inputRef.current?.click();
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
        className={`flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-12 text-center transition-colors ${
          disabled
            ? "cursor-not-allowed border-black/10 opacity-50 dark:border-white/10"
            : "cursor-pointer border-black/20 hover:border-black/40 dark:border-white/20 dark:hover:border-white/40"
        } ${isDragging ? "border-blue-500 bg-blue-500/5" : ""}`}
      >
        <p className="text-sm font-medium">Drop a file here, or click to browse</p>
        <p className="text-xs opacity-60">PNG, JPG, PDF, or SVG</p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          disabled={disabled}
          className="hidden"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>
      {error && <p className="mt-2 text-sm text-red-500">{error}</p>}
    </div>
  );
}
