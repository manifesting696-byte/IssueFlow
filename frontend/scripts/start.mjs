import { cpSync, mkdirSync } from "node:fs";
import { spawn } from "node:child_process";
mkdirSync(".next/standalone/.next", { recursive: true });
cpSync(".next/static", ".next/standalone/.next/static", { recursive: true });
const child = spawn(process.execPath, [".next/standalone/server.js"], {
  stdio: "inherit",
  env: {
    ...process.env,
    HOSTNAME: process.env.HOSTNAME || "127.0.0.1",
    PORT: process.env.PORT || "3000",
  },
});
child.on("exit", (code) => process.exit(code ?? 1));
