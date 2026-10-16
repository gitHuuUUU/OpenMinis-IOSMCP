---
name: local-local-crypto-recovery
description: Identify encodings, hashes and encrypted file formats, perform offline password recovery or cryptographic analysis using the installed local tools; use for concrete recovery and CTF crypto tasks.
---

Read references/deployment.md. Classify encoding versus hash versus encryption before choosing tooling. Use CyberChef for explicit recipes, Ciphey for common encoding discovery, pyWhat/hashID as tentative classifiers, Hashcat/John for offline candidate verification, RsaCtfTool for evidenced RSA weaknesses, and crypto-env for known-key decryption. Inspect format and KDF, preserve originals and record resource budget. Verify recovered plaintext or password against the actual artifact. Do not claim arbitrary strong encryption is breakable or that CPU device discovery validates GPU acceleration.

Toolkit root: D:/Codex/小飞机/ai-toolkit.
