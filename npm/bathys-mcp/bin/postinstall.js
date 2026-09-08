#!/usr/bin/env node
/**
 * postinstall: make `npm i -g bathys-mcp` a complete one-command setup.
 * Installs the Python package (pip install bathys) when python is available,
 * then prints the next step (bathys-mcp install / bathys install).
 * Never fails the npm install: absence of python is reported, not thrown.
 */

const { spawnSync } = require("child_process");

function pythonBin() {
  const bins = process.platform === "win32" ? ["python", "py"] : ["python3", "python"];
  for (const bin of bins) {
    const res = spawnSync(bin, ["--version"], { encoding: "utf8" });
    if (res.status === 0) return bin;
  }
  return null;
}

const py = pythonBin();
if (!py) {
  console.log(
    "[bathys-mcp] Python не найден — установите Python ≥3.10 и выполните:\n" +
    "             pip install bathys\n" +
    "             bathys install   # автоподключение к найденным харнессам"
  );
  return;
}

console.log("[bathys-mcp] Устанавливаю Python-пакет bathys (pip)…");
const res = spawnSync(py, ["-m", "pip", "install", "--quiet", "--upgrade", "bathys"], {
  stdio: "inherit",
});
if (res.status !== 0) {
  console.log(
    "[bathys-mcp] pip install bathys не удался — выполните вручную, затем:\n" +
    "             bathys install"
  );
  return;
}
console.log(
  "[bathys-mcp] Готово. Следующий шаг — подключить харнессы:\n" +
  "             bathys-mcp install   (или: bathys install)\n" +
  "             bathys-mcp doctor    # диагностика стека"
);