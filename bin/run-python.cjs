#!/usr/bin/env node
"use strict";

const path = require("node:path");
const { spawn } = require("node:child_process");

function candidates() {
  const configured = process.env.PYTHON;
  const list = [];
  if (configured) {
    list.push({ command: configured, prefix: [] });
  }
  if (process.platform === "win32") {
    list.push({ command: "py", prefix: ["-3"] });
    list.push({ command: "python", prefix: [] });
    list.push({ command: "python3", prefix: [] });
  } else {
    list.push({ command: "python3", prefix: [] });
    list.push({ command: "python", prefix: [] });
  }
  return list;
}

function runPython(scriptName) {
  const scriptPath = path.resolve(__dirname, "..", "scripts", scriptName);
  const options = candidates();

  function launch(index) {
    if (index >= options.length) {
      process.stderr.write("ERROR: Python 3.10 or newer was not found. Set PYTHON to an executable path.\n");
      process.exitCode = 127;
      return;
    }
    const selected = options[index];
    const child = spawn(
      selected.command,
      [...selected.prefix, "-B", scriptPath, ...process.argv.slice(2)],
      { shell: false, stdio: "inherit", windowsHide: true }
    );
    let started = false;
    child.once("spawn", () => {
      started = true;
    });
    child.once("error", (error) => {
      if (!started && error && error.code === "ENOENT") {
        launch(index + 1);
        return;
      }
      process.stderr.write(`ERROR: failed to launch Python: ${error.message}\n`);
      process.exitCode = 1;
    });
    child.once("exit", (code, signal) => {
      if (signal) {
        try {
          process.kill(process.pid, signal);
        } catch (_error) {
          process.exitCode = 1;
        }
        return;
      }
      process.exitCode = Number.isInteger(code) ? code : 1;
    });
    for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
      process.once(signal, () => {
        try {
          child.kill(signal);
        } catch (_error) {
          process.exitCode = 1;
        }
      });
    }
  }

  launch(0);
}

module.exports = { runPython };
