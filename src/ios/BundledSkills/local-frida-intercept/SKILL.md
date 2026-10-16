---
name: local-frida-intercept
description: Hook network functions with Frida. Trigger: frida, hook send, hook recv, intercept traffic, capture packets.
tool: Frida (pip: frida-tools)
---
# frida-intercept

## Trigger
`frida, hook send, hook recv, intercept traffic, capture packets`

## Flow
```
frida -n $PROCESS -l hook.js -> output send/recv/WSASend hook script with hexdump
```

## Script
`scripts/frida_intercept.py`
