---
name: minis-reverse-runtime
description: Install, diagnose, and use the pinned REA 6.4.0 reverse-engineering runtime and its local MCP integration in the Minis Alpine guest.
---

# Minis REA runtime

Use this skill when a user asks to install or diagnose the app's bundled REA CLI/MCP, or to select a suitable REA analysis tool.

## Install and verify

- Run `python3 /usr/local/lib/minis-reverse-tools/rea_install.py install` inside the Alpine guest.
- Treat the last stdout line as a JSON result. Success requires `status == "installed"`, `installed == true`, `version == "6.4.0"`, `mcp.initialize == true`, `mcp.toolsList == true`, and `registrationReady == true`.
- The app registers the server only after those checks succeed. Its stdio command is `/usr/local/bin/rea` with argument `mcp`; do not infer registration from a leftover binary or package directory.
- Run `python3 /usr/local/lib/minis-reverse-tools/rea_install.py doctor` to recheck package, doctor status, and MCP initialize/tools-list. Report the JSON fields accurately.
- `doctor.backendStatus` is independent of MCP readiness. REA may serve MCP while optional analysis providers are unavailable. Never claim Ghidra, Hopper, IDA, or another backend is ready unless the diagnostic evidence says so; do not install commercial analysis software as part of this runtime installer.

## Runtime boundaries

- REA runs in the Alpine Linux guest. It can analyze files accessible there and tools/providers exposed to that guest.
- An iSH/Alpine process is not in the iOS host app's native process address space. Do not claim that guest REA directly hooks or inspects arbitrary native iOS processes; a native iOS integration requires a separate host-side bridge/runtime and explicit target visibility.
- The installation pins `rea-agents@6.4.0`, keeps `package-lock.json`, uses npm with install scripts disabled, and copies the package-shipped `reverse-engineer-anything` skill and references without overwriting a preexisting user skill.
- The installer does not install commercial IDA or Frida and does not claim those tools are available.

## Reporting

State separately whether the package version, CLI version, MCP `initialize`, MCP `tools/list`, official skill copy, and backend doctor checks passed. A failed probe means MCP is not registered as installed, even if package files or a CLI wrapper remain. Distinguish desktop/WSL tests from Alpine aarch64 and on-device verification.
