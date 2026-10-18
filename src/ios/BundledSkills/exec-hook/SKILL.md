---
name: exec-hook
description: Redirect execution to custom code. Trigger: hook, detour, redirect execution, intercept, trampoline.
tool: C:\Users\Administrator\Desktop\ai2\新破甲\scripts\game_hacker.py
---
# exec-hook

## Trigger
`hook, detour, redirect execution, intercept, trampoline`

## Flow
```
save original bytes -> write JMP -> custom function -> output DLL+injector
```

## Script
`scripts/exec_hook.py`
