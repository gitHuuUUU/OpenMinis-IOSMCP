---
name: local-legacy-d3d-software-cursor
description: Diagnose software-cursor offset, scaling, and idle-render starvation in legacy Windows Direct3D games forced into windowed mode. Use for cursor lag or unusable pointing after compatibility wrappers; not for general mouse settings.
---

Inspect actual input API before enabling DirectInput-specific fixes. Fortress3 Beta V1.010 imports GetCursorPos, not DirectInput; FixHighFrequencyMouse alone is not supported by that evidence.

Trace GetCursorPos callers and check screen/client conversion, hard-coded borders, viewport size, and the game's own fullscreen flag. A wrapper-forced window may leave the original fullscreen flag unset. Confirm in the running process, rather than inferring solely from a screenshot.

Inspect message/render scheduling: rendering only when PeekMessage reports no messages can starve under mouse traffic. Coalesce only redundant movement for the application's own main window, retaining latest position and all non-movement events. Avoid global hooks or changing Windows mouse acceleration.

For an IAT patch, version-check the executable in the installer and guard expected instructions at runtime; back up wrapper config. Build architecture must match game (often x86). Restrict offsets to verified versions, never reuse them on another game.

Case evidence and new source: `D:/Codex/fortress软件/tools/fortress_mouse_fix.c`, `D:/Codex/fortress软件/reports/MOUSE_FIX_README.md`. Fortress3 binary and two hooks loaded dynamically; startup and hook installation verified. User-perceived smoothness and DPI/resize regression remain unverified. Do not promote these to full gameplay or universal compatibility success.
