---
name: local-patch-rollback
description: Restore original from backup. Trigger: restore, rollback, undo, revert, original file.
tool: cp
---
# patch-rollback

## Trigger
`restore, rollback, undo, revert, original file`

## Flow
```
cp $TARGET.bak $TARGET -> sha256 verify
```

## Script
`scripts/patch_rollback.py`
