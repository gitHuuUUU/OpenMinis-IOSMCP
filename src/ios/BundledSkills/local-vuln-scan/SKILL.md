---
name: local-vuln-scan
trigger: vuln 漏洞 nuclei cve
tools: nuclei vuln_scanner.py
---

# 版本验证

## Phase 1
`nuclei -u {TARGET} -severity critical,high,medium -stats -o exports/verify_{TARGET}.txt`

## Phase 2
`python Skills/vuln-scan/scripts/vuln_scanner.py --target {TARGET} --verify {CVE-ID}`

输出 → exports/verify_{TARGET}.txt
