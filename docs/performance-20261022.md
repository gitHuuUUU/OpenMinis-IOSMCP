# Performance candidate (2026-10-22)

- iOS 15 mounts the last 40 messages initially. Load-earlier adds 40 while retaining the previous first-message anchor. History and outbound model context are not truncated.
- The native scroll probe owns interaction detection; removed the competing SwiftUI drag recognizer. Streaming UI updates resume after interaction/disappearance; collection-view bottom writes refuse active drag/deceleration.
- Fast completion polling is independent of progress rendering (at most once per second). Each child gets at most two concurrent tools, preventing the per-session cap multiplying unchecked during fan-out.
- With adaptive thermal enabled, fair temperature falls back to four tools/two children; serious/critical or low-power admits one. Already-running operations are not force-cancelled.
- Local ZIP import also accepts manifestless SKILL.md exports and documents-only Markdown exports, normalizing to the existing preview/confirmation/validation lifecycle. Unix executable permission bits alone no longer reject text resources; executable signatures/extensions and instruction checks remain enforced.
- RAR4/RAR5 now use a pinned, statically linked libarchive reader (no shell, no jailbreak-only decoder). Encrypted and multipart archives are not supported. Native compile and format fixtures are required before treating this as verified. Archive byte/count limits remain, as the existing decoder retains expanded payloads in memory. Removing them would risk more memory pressure and heat. Script-containing archives are still not accepted as declarative extensions.

Verification: local Python source-contract/unit suites; native Swift runtime, iPhone scroll performance, thermal behavior and install compatibility require separate validation. No measured speedup or resolved device bug is claimed.
