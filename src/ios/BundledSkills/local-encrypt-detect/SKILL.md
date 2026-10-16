---
name: local-encrypt-detect
description: Detect encryption from traffic patterns. Trigger: encrypt, decrypt, crypto, cipher, aes, xor, base64 encoding.
tool: Python + Frida
---
# encrypt-detect

## Trigger
`encrypt, decrypt, crypto, cipher, aes, xor, base64 encoding`

## Flow
```
capture pre/post buffers -> entropy analysis -> output encryption type + decrypt function
```

## Script
`scripts/encrypt_detect.py`
