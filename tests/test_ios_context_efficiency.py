"""Source-wiring regression checks; native Swift execution requires the iOS CI runner."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1] / "src/ios/Agent/Chat"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class ContextEfficiencyWiringTests(unittest.TestCase):
    def test_real_send_uses_composed_prompt_on_all_paths(self):
        vm = read("AIChatViewModel.swift")
        self.assertIn("PromptLibraryStore.shared.compose(base: baseSystemPrompt)", vm)
        self.assertIn("var userSystemPrompt = composedBaseSystemPrompt", vm)
        self.assertIn("userSystemPrompt = composedBaseSystemPrompt", vm)
        self.assertNotRegex(vm, r"baseSystemPrompt:\s*baseSystemPrompt,")
        self.assertEqual(vm.count("baseSystemPrompt: composedBaseSystemPrompt,"), 3)

    def test_expert_flags_affect_real_context(self):
        vm = read("AIChatViewModel.swift")
        for snippet in (
            "profile.injectFullRules ? baseSystemPrompt",
            "profile.injectBaseline ?",
            "helperConfig?.expertProfile?.injectSkills != false",
            "helperConfig?.expertProfile?.injectMemory != false",
            "if profile.injectProjectRules",
            "ExpertProfileStore.shared.boundSkillFragment(profile: profile)",
        ):
            self.assertIn(snippet, vm)

    def test_summary_preserves_open_requests_and_bounds_duplication(self):
        compact = read("AIChatViewModel+Compaction.swift")
        self.assertIn("static let compactKeepRecentUserTurns: Int = 1", compact)
        self.assertIn("which user requests remain unfinished", compact)
        self.assertIn('"Still pending"', compact)
        self.assertIn("Preserve unfinished user goals", compact)

    def test_offload_never_drops_data_without_recoverable_ref(self):
        offload = read("AIChatViewModel+Offloading.swift")
        self.assertIn("private func offloadContextContent", offload)
        self.assertRegex(offload, r"offloadContextContent\([^\n]+\) -> String\?")
        self.assertRegex(offload, r"offloadContextImage\([^\n]+\) -> String\?")
        self.assertIn("guard snapshotPath != nil else { continue }", offload)
        self.assertIn("guard let snap = offloadContextImage", offload)
        self.assertIn("guard !paths.isEmpty else { continue }", offload)
        self.assertIn("if msgIdx == lastUserTurn { continue }", offload)
        self.assertIn("paths.joined(separator:", offload)

    def test_statistics_do_not_claim_savings(self):
        vm = read("AIChatViewModel.swift")
        self.assertIn("var contextEfficiencyStats: ContextEfficiencyStats", vm)
        self.assertIn("ensureContextFixedTokens()\n        let last", vm)
        self.assertIn("contextFixedTokens - oldTokens + newTokens", vm)
        self.assertIn("actualFreshInputTokens: sessionInputTokens", vm)
        self.assertIn("estimatedNextContextTokens: measureOutboundContextTokens()", vm)
        fields = re.search(r"struct ContextEfficiencyStats \{(.+?)\n    \}", vm, re.S)
        self.assertIsNotNone(fields)
        self.assertNotIn("saved", fields.group(1).lower())


if __name__ == "__main__":
    unittest.main()
