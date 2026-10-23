"""Static coexistence contracts, not an iPhone/network integration test.

The checked-in baseline was computed from `git show ed88573:<path>` so these
checks also work in a shallow CI checkout or an exported matching source ZIP.
Only the new app-owned Cockpit entry is excluded from the original registry hash.
"""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / "tools/cockpit_coexistence_baseline.json").read_text(encoding="utf-8"))


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def block(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


class CockpitCoexistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = source("src/ios/Views/Providers/AddProviderView.swift")
        cls.store = source("src/ios/Providers/ProviderConfigStore.swift")
        cls.catalog_source = source("src/ios/Providers/ModelsDevAPI.swift")
        raw = (ROOT / "src/ios/Resources/models-dev-api.json").read_bytes()
        cls.catalog_raw = raw
        cls.catalog = json.loads(raw)

    def test_all_original_223_providers_and_order_preserved(self):
        original = {key: value for key, value in self.catalog.items() if key != "cockpit"}
        self.assertEqual(len(original), BASELINE["catalog_provider_count"])
        canonical = json.dumps(original, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(digest(canonical), BASELINE["catalog_sha256"])
        self.assertEqual(len(self.catalog), 224)

    def test_catalog_utf8_without_bom_and_real_models_only(self):
        self.assertFalse(self.catalog_raw.startswith(b"\xef\xbb\xbf"))
        provider = self.catalog["cockpit"]
        self.assertEqual(provider["id"], "cockpit")
        self.assertEqual(provider["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(provider["env"], ["COCKPIT_API_KEY"])
        self.assertEqual(set(provider["models"]), {"gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol"})
        for model_id, model in provider["models"].items():
            self.assertEqual(model["id"], model_id)
            self.assertNotIn("cost", model, "Unknown gateway prices must not be invented")

    def test_protocol_identity_signing_settings_and_existing_features_unchanged(self):
        for path, expected in BASELINE["files"].items():
            with self.subTest(path=path):
                self.assertEqual(digest(source(path)), expected)

    def test_keychain_storage_and_existing_session_bindings_unchanged(self):
        keychain = self.store.split("enum ProviderKeychainHelper {", 1)[1]
        self.assertEqual(digest(keychain), BASELINE["keychain_sha256"])
        bindings = block(self.store, "    func binding(for sessionId:", "    func applyConfig(")
        self.assertEqual(digest(bindings), BASELINE["session_binding_sha256"])

    def test_cockpit_is_additive_row_not_replacement_for_protocols(self):
        picker = block(self.ui, "private var typePickerSection:", "private func applyCockpitPreset()")
        self.assertIn("applyCockpitPreset()", picker)
        self.assertIn("Text(CockpitGatewayPreset.name)", picker)
        self.assertIn("ForEach(visibleProviderTypes", picker)
        self.assertIn("ProviderType.allCases.filter", self.ui)
        self.assertIn("voiceProviderSection", picker)
        self.assertIn("showImportFile = true", picker)

    def test_preset_has_separate_api_key_account_and_no_double_v1(self):
        preset = block(self.ui, "private func applyCockpitPreset()", "private var cockpitBaseURLIsValid")
        for token in ("selectedType = .openAI", "selectedCredential = .apiKey",
                      "enteredViaCockpitPreset = true", "enteredViaVoiceTemplate = false",
                      "customBaseURLInput = CockpitGatewayPreset.lanBaseURL",
                      "appendV1SuffixInput = false", "useResponsesAPI = false"):
            self.assertIn(token, preset)
        base = block(self.ui, "private var customBaseURLSection:", "private var defaultBaseURL:")
        self.assertIn("CockpitGatewayPreset.lanBaseURL", base)
        self.assertIn("CockpitGatewayPreset.tailscaleBaseURL", base)
        self.assertGreaterEqual(base.count("appendV1SuffixInput = false"), 2)

    def test_instance_key_written_before_discovery_and_isolated_by_instance_id(self):
        save = block(self.ui, "private func saveApiKeyInstance()", "private func saveOAuthInstance()")
        self.assertIn("let instance = ProviderInstance(", save)
        key_save = "ProviderKeychainHelper.saveAPIKey(trimmedKey, instanceId: instance.id)"
        self.assertIn(key_save, save)
        self.assertLess(save.index(key_save), save.index("store.addInstance(instance)"))
        self.assertNotIn("id: Cockpit", save)
        self.assertNotIn("defaultPrimaryGroupId", save)
        self.assertNotIn("sessionBindings", save)
        api_key = block(self.ui, "private var emptyKeyAllowedForCurrentInput:", "private var canSaveCurrentInput:")
        self.assertIn("if enteredViaCockpitPreset { return false }", api_key)

    def test_preset_back_clears_state_without_changing_other_accounts(self):
        back = block(self.ui, "private func goBack()", "private func cleanupAndDismiss()")
        preset_back = back.split("if enteredViaVoiceTemplate || enteredViaCockpitPreset {", 1)[1].split("return", 1)[0]
        for token in ("enteredViaCockpitPreset = false", "configuringVendorName = nil",
                      'apiKeyInput = ""', 'customBaseURLInput = ""',
                      "appendV1SuffixInput = true", "useResponsesAPI = false"):
            self.assertIn(token, preset_back)
        self.assertNotIn("store.updateInstance", back)
        self.assertNotIn("store.removeInstance", back)

    def test_cockpit_invalid_url_or_empty_key_cannot_save(self):
        can_save = block(self.ui, "private var canSaveCurrentInput:", "private func saveCurrentInputAndExit()")
        self.assertIn("if enteredViaCockpitPreset && !cockpitBaseURLIsValid { return false }", can_save)
        self.assertIn("!apiKeyInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || emptyKeyAllowedForCurrentInput", can_save)
        save = block(self.ui, "private func saveApiKeyInstance()", "private func saveOAuthInstance()")
        self.assertIn("guard !enteredViaCockpitPreset || cockpitBaseURLIsValid else", save)
        self.assertIn("guard !trimmedKey.isEmpty || emptyKeyAllowedForCurrentInput else { return }", save)
        self.assertIn(".disabled(!canSaveCurrentInput || isSaving)", self.ui)
        validation = block(self.ui, "private var cockpitBaseURLIsValid:", "// MARK: - Step 2")
        for check in ('["http", "https"].contains(scheme)', "!host.isEmpty", "url.user == nil",
                      "url.password == nil", "url.query == nil", "url.fragment == nil"):
            self.assertIn(check, validation)

    def test_seed_and_fallback_are_strictly_instance_scoped(self):
        identity = block(self.store, "private static func isCockpitGateway(", "/// Fetch models from")
        for token in ("instance.credentialType == .apiKey", "instance.providerType == .openAI",
                      "CockpitGatewayPreset.matches(baseURL: instance.effectiveCustomBaseURL)"):
            self.assertIn(token, identity)
        add = block(self.store, "func addInstance(_ instance:", "/// Sync voice-template")
        seed = add.split("} else if Self.isCockpitGateway(instance) {", 1)[1].split("} else if", 1)[0]
        self.assertIn("ModelEntry(providerInstanceId: instance.id, model: $0)", seed)
        self.assertIn("Task { await refreshModels(for: instance) }", seed)
        self.assertNotIn("defaultPrimaryGroupId", add)
        self.assertNotIn("sessionBindings", add)
        fallback = block(self.store, "static func fetchModelsWithFallback(", "/// Resolve the effective API base URL")
        self.assertIn("if isThirdParty && !isCockpitGateway(instance)", fallback)
        self.assertIn('source: "api"', fallback)
        self.assertIn('source: "models.dev"', fallback)
        refresh = block(self.store, "func refreshModels(for instance:", "private func autoRefreshModels(")
        self.assertIn("replaceEntries(for: instance.id", refresh)

    def test_gateway_metadata_does_not_leak_into_other_ports_or_providers(self):
        preset = self.catalog_source.split("enum ModelsDevAPI {", 1)[0]
        for token in ('url.scheme?.lowercased() == "http"', "url.port == 61722",
                      'return path.isEmpty || path == "/v1"', "url.user == nil",
                      "url.password == nil", "url.query == nil", "url.fragment == nil"):
            self.assertIn(token, preset)
        fetch = block(self.catalog_source, "static func fetchModels(forBaseURL", "private static func buildModels(")
        self.assertEqual(fetch.count("guard provider.id != CockpitGatewayPreset.providerID"), 2)
        for method in ("buildAggregateIndex(", "buildStage2Index("):
            definition = self.catalog_source.split("private static func " + method, 1)[1]
            definition = definition.split("\n    }", 1)[0]
            self.assertIn("key != CockpitGatewayPreset.providerID", definition)

    def test_disk_network_and_bundle_use_additive_catalog_overlay(self):
        parse = block(self.catalog_source, "private static func parseRegistry(", "// MARK: - Bundled Fallback")
        self.assertIn("CockpitGatewayPreset.mergingLocalProvider(", parse)
        self.assertIn("into: parsed, localProvider: bundledCockpitProvider", parse)
        cache = block(self.catalog_source, "private static func loadRegistry()", "private static func parseRegistry(")
        self.assertGreaterEqual(cache.count("parseRegistry("), 2)
        self.assertIn("cachedRegistry = parsed", cache)
        self.assertIn("saveDiskCache(data)", cache)

    def test_same_api_key_on_other_endpoints_cannot_share_model_cache(self):
        api = source("src/ios/Providers/OpenAI/OpenAIModelsAPI.swift")
        fetch = block(api, "static func fetchModels(apiKey:", "// MARK: - [T-codex-model-discovery]")
        self.assertIn("APIKeyModelsCacheKey(endpoint: url.absoluteString", fetch)
        for token in ("apiKey: apiKey", "userAgent: userAgent", "filterOpenAIOnly: !isCustomBase",
                      "OpenAIModelsCache.load(key: cacheKey)", "OpenAIModelsCache.save(models, key: cacheKey)"):
            self.assertIn(token, fetch)
        self.assertNotIn("credential: apiKey", fetch)
        oauth = block(api, "    static func fetchModelsOAuth(", "    private static func performFetch(")
        self.assertEqual(digest(oauth), BASELINE["openai_oauth_sha256"])

    def test_successful_gateway_discovery_uses_own_metadata_without_dropping_new_models(self):
        fetch = block(self.store, "static func fetchModelsForInstance(", "/// Result of a model fetch")
        for protocol in ("openAI", "openAIResponses"):
            branch = fetch.split("case (." + protocol + ", .apiKey):", 1)[1].split("case (", 1)[0]
            self.assertIn("let models = try await OpenAIModelsAPI.fetchModels(", branch)
            self.assertIn("ModelsDevAPI.cockpitModels(models, forBaseURL: isCockpitGateway(instance) ? customBase : nil)", branch)
        remap = block(self.catalog_source, "static func cockpitModels(", "private static func buildModels(")
        self.assertIn("guard CockpitGatewayPreset.matches(baseURL: baseURL) else { return models }", remap)
        self.assertIn("return models.map { model in", remap)
        self.assertIn("if let own = knownModels[model.id]", remap)
        self.assertIn("maxOutputTokens: own.maxOutputTokens", remap)
        self.assertIn("provider: CockpitGatewayPreset.name", remap)
        self.assertIn("gatewayModel.effortDeclarationIsAuthoritative = nil", remap)
        self.assertNotIn("models.filter", remap)

    def test_no_gateway_credentials_bundled_or_auto_written(self):
        self.assertFalse({"api_key", "apiKey", "password", "token"} & set(self.catalog["cockpit"]))
        for text in (json.dumps(self.catalog["cockpit"]), self.ui, self.catalog_source):
            self.assertIsNone(re.search(r"(?:agt_codex_|sk-proj-|sk-cockpit-)[A-Za-z0-9_-]{12,}", text))
            self.assertNotIn("codex_local_access.json", text)
        preset = block(self.ui, "private func applyCockpitPreset()", "private var cockpitBaseURLIsValid")
        self.assertNotIn("apiKeyInput =", preset)
        self.assertNotIn("saveAPIKey", preset)
        self.assertNotIn("addInstance", preset)


if __name__ == "__main__":
    unittest.main()
