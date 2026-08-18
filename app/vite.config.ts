import { defineConfig } from "vite";

export default defineConfig({
  // maplibre-gl carrega seu worker via `new Worker(new URL(...), {type:'module'})`;
  // o pré-bundler do Vite (esbuild) reescreve isso de um jeito que trava a
  // requisição do worker pra sempre. Excluir do pré-bundle resolve.
  optimizeDeps: { exclude: ["maplibre-gl"] },
});
