import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { connect } from "node:net";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const API_PORT = 8000;

function portOpen(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const s = connect({ port, host: "127.0.0.1" });
    s.once("connect", () => { s.destroy(); resolve(true); });
    s.once("error", () => resolve(false));
  });
}

/**
 * npm run dev 한 번으로 백엔드(FastAPI, 8000번)도 함께 켠다.
 * - 8000번에 이미 서버가 있으면 그것을 쓰고, backend/.venv가 없으면 안내만 하고 화면만 켠다.
 * - 백엔드가 응답할 때까지 기다린 뒤 화면 주소를 출력한다(1분 안팎).
 * - VITE_API_BASE로 다른 백엔드를 지정했으면 켜지 않는다. 터미널에서 Ctrl+C를 누르면 둘 다 꺼진다.
 */
function backend(): Plugin {
  let proc: ChildProcess | null = null;
  const stop = () => {
    if (!proc || proc.exitCode !== null) return;
    if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(proc.pid), "/T", "/F"], { stdio: "ignore" });
    else proc.kill();
    proc = null;
  };
  return {
    name: "segnal-backend",
    apply: "serve",
    async configureServer(server) {
      const log = server.config.logger;
      if (process.env.VITE_API_BASE) return;
      if (await portOpen(API_PORT)) {
        log.info(`[backend] ${API_PORT}번에 이미 켜진 백엔드를 사용합니다.`);
        return;
      }
      const dir = fileURLToPath(new URL("../backend/", import.meta.url));
      const py = join(dir, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
      if (!existsSync(py)) {
        log.warn(`[backend] ${py} 가 없어 화면만 켭니다. README대로 백엔드를 먼저 설치하세요.`);
        return;
      }
      log.info("[backend] 백엔드를 켜는 중입니다. 준비되면 화면 주소가 나옵니다 (1분 안팎)...");
      proc = spawn(py, ["-m", "uvicorn", "main:app", "--port", String(API_PORT), "--log-level", "warning"], { cwd: dir, stdio: "inherit" });
      let exited = false;
      proc.once("exit", (code) => { exited = true; if (code) log.warn(`[backend] 백엔드가 종료되었습니다 (코드 ${code}).`); });
      server.httpServer?.once("close", stop);
      process.once("exit", stop);
      const t0 = Date.now();
      let ready = false;
      while (!exited && Date.now() - t0 < 180_000 && !(ready = await portOpen(API_PORT))) await new Promise((r) => setTimeout(r, 500));
      if (ready) log.info(`[backend] 준비됨: http://localhost:${API_PORT}`);
      else if (!exited) log.warn("[backend] 3분 안에 응답이 없습니다. 위의 백엔드 로그를 확인하세요.");
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), backend()],
  // 백엔드 CORS가 5173번만 허용하므로, 5173번이 이미 쓰이면 다른 포트로 넘어가지 않고 바로 알린다
  server: { port: 5173, strictPort: true },
});
