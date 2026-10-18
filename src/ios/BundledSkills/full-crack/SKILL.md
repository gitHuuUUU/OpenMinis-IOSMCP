---
name: full-crack
description: Complete cracking workflow. Trigger: full crack, complete crack, crack workflow, 完整破解.
type: chain
---
# full-crack

## Chain
1. `string-extract` — Extract auth-related strings
2. `function-decompile` — Decompile verification function
3. `jump-patch` — Patch conditional jump
4. `keygen-build` — Build keygen if serial-based
5. `patch-apply` — Apply final patch

## Execution
Execute each step sequentially. Output combined results.
