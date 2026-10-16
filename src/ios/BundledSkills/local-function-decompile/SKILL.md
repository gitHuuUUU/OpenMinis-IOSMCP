---
name: local-function-decompile
description: Decompile and identify key functions. Trigger: function, decompile, pseudocode, routine, subroutine.
tool: C:\Users\Administrator\Desktop\ai2\新破甲\Tool\Ghidrafessional 9.2\ghidraRun.bat
---
# function-decompile

## Trigger
`function, decompile, pseudocode, routine, subroutine`

## Flow
```
Ghidra open $TARGET -> locate functions -> output pseudocode
```

## Script
`scripts/function_decompile.py`
