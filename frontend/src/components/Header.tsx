import { Box } from "lucide-react";

export default function Header() {
  return (
    <header className="flex items-center gap-3 border-b border-border px-6 py-4">
      <div className="flex size-8 items-center justify-center rounded-lg bg-primary">
        <Box className="size-5 text-primary-foreground" />
      </div>
      <span className="text-lg font-semibold tracking-tight">Sivi</span>
    </header>
  );
}
