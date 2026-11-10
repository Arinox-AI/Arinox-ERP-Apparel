import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Single self-contained bundle (the platform serves one index.html). tools in build.sh inline the output.
export default defineConfig({
  plugins: [react()],
  base: "./",
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "dist", assetsInlineLimit: 100_000_000, cssCodeSplit: false, sourcemap: false, chunkSizeWarningLimit: 4000,
    rollupOptions: { output: { inlineDynamicImports: true, entryFileNames: "app.js", assetFileNames: "app.[ext]" } },
  },
});
