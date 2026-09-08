#!/usr/bin/env node
/**
 * bathys-mcp — thin installer wrapper around the Python `bathys` package.
 *
 * The real server is a Python stdio MCP server distributed on PyPI. This npm
 * package exists so Node-first users can `npm install -g bathys-mcp` and get
 * the same end-to-end setup: python package + harness integration.
 *
 * Commands:
 *   bathys-mcp            run the MCP server over stdio (delegates to `bathys`)
 *   bathys-mcp install    run `bathys install` (harness auto-integration)
 *   bathys-mcp doctor     run `bathys-doctor`
 *   bathys-mcp print-config
 */

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

function findBathys() {
  const candidates = [
    path.join(__dirname, "..", "python", "bin", "bathys"), // local venv from postinstall
  ];
  const which = process.platform === "win32" ? "where" : "which";
  for (const cmd of ["bathys", "bathys-doctor"]) {
    const res = spawnSync(which, [cmd], { encoding: "utf8" });
    if (res.status === 0 && res.stdout) {
      candidates.push(res.stdout.trim().split("\n")[0]);
    }
  }
  for (const c of candidates) {
    if (c && fs.existsSync(c)) return c;
  }
  return null;
}

function pythonAvailable() {
  const bins = process.platform === "win32" ? ["python", "py"] : ["python3", "python"];
  for (const bin of bins) {
    const res = spawnSync(bin, ["--version"], { encoding: "utf8" });
    if (res.status === 0) return bin;
  }
  return null;
}

const cmd = process.argv[2];

if (cmd === "install" || cmd === "doctor" || cmd === "print-config" || cmd === "help" || cmd === "--help") {
  const bathys = findBathys();
  if (!bathys) {
    const py = pythonAvailable();
    console.error("bathys не найден. Установите Python-пакет:" + (py ? "" : " (python не найден в PATH)"));
    console.error(py ? `  ${py} -m pip install bathys` : "  установите Python ≥3.10, затем: pip install bathys");
    process.exit(1);
  }
  const args = cmd === "install" ? ["install", ...process.argv.slice(3)]
    : cmd === "doctor" ? ["doctor", ...process.argv.slice(3)]
    : cmd === "print-config" ? ["install", "--print-config"]
    : ["--help"];
  const res = spawnSync(bathys, args, { stdio: "inherit" });
  process.exit(res.status || 0);
}

// default: run the MCP server over stdio
const bathys = findBathys();
if (!bathys) {
  console.error("bathys не найден. Сначала установите Python-пакет: pip install bathys");
  process.exit(1);
}
const res = spawnSync(bathys, process.argv.slice(2), { stdio: "inherit" });
process.exit(res.status || 0);