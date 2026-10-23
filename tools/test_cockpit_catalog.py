"""Cockpit catalog regression, including unchanged production Swift on macOS.

    python3 tools/test_cockpit_catalog.py --require-swift

The only native test double is AppLogger plus the intercepted HTTP transport.
ModelsDevAPI, URL matching, local overlay, cache IO, refresh, model types and
release ranking all come from production sources. No live gateway/key is used.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/ios/Providers/ModelsDevAPI.swift"
CATALOG = ROOT / "src/ios/Resources/models-dev-api.json"
MODELS = {"gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol"}


class CatalogContracts(unittest.TestCase):
    def test_presets_and_no_embedded_secret(self):
        data = CATALOG.read_bytes()
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        catalog = json.loads(data)
        self.assertEqual(len(catalog), 224)
        self.assertEqual(len({k: v for k, v in catalog.items() if k != "cockpit"}), 223)
        local = catalog["cockpit"]
        self.assertEqual(local["api"], "http://192.168.0.39:61722/v1")
        self.assertEqual(local["env"], ["COCKPIT_API_KEY"])
        self.assertEqual(local["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(set(local["models"]), MODELS)
        self.assertNotIn("api_key", local)
        self.assertNotIn("apiKey", local)
        for model in local["models"].values():
            self.assertNotIn("cost", model)  # unknown is NOT free/zero
            self.assertNotIn("output", model["limit"])
            self.assertNotIn("release_date", model)

    def test_every_decode_uses_local_overlay(self):
        source = SOURCE.read_text(encoding="utf-8")
        parse = source.split("private static func parseRegistry(", 1)[1].split("// MARK:", 1)[0]
        self.assertIn("CockpitGatewayPreset.mergingLocalProvider(", parse)
        for name in ("loadRegistry()", "refreshFromNetwork()"):
            body = source.split("private static func " + name, 1)[1]
            self.assertIn("parseRegistry(", body.split("private static func", 1)[0])

    def test_private_metadata_is_not_cross_provider_inference(self):
        source = SOURCE.read_text(encoding="utf-8")
        for name in ("buildStage2Index(", "buildAggregateIndex(", "releaseIndex()"):
            method = source.split("static func " + name, 1)[1].split("\n    }", 1)[0]
            self.assertIn("guard key != CockpitGatewayPreset.providerID", method)


SWIFT_TEST = r'''
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

struct AppLogger {
    init(category: String) {}
    func info(_ message: String) {}
    func error(_ message: String) {}
}

final class CatalogHTTPFixture: URLProtocol {
    static var data = Data()
    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.absoluteString == "https://models.dev/api.json"
    }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let response = HTTPURLResponse(url: request.url!, statusCode: 200,
            httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Self.data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

extension ModelsDevAPI {
    static func runCockpitCatalogTests() async throws {
        var checks = 0
        func check(_ condition: @autoclosure () -> Bool, _ label: String) {
            precondition(condition(), "FAIL: " + label)
            checks += 1
            print("PASS: " + label)
        }
        let expected = Set(["gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol"])
        for base in [CockpitGatewayPreset.lanBaseURL, CockpitGatewayPreset.tailscaleBaseURL] {
            for candidate in [base, base + "/", base + "///", String(base.dropLast(3)),
                              String(base.dropLast(3)) + "/", "  " + base + " \n"] {
                check(CockpitGatewayPreset.matches(baseURL: candidate), "exact alias accepted: " + candidate)
            }
        }
        let denied: [String?] = [nil, "", "not a url", "http://192.168.0.39:1234/v1",
            "http://192.168.0.39/v1", "https://192.168.0.39:61722/v1",
            "http://192.168.0.39:61722/v2", "http://192.168.0.39:61722/another/v1",
            "http://192.168.0.39:61722/v1/chat/completions", "http://192.168.0.39:61722/v1?key=no",
            "http://192.168.0.39:61722/v1#other", "http://user@192.168.0.39:61722/v1",
            "http://192.168.0.39.evil:61722/v1", "http://100.116.107.1:61723/v1",
            "http://100.116.107.1:61722/%76%31", "http://127.0.0.1:61722/v1"]
        for candidate in denied {
            check(!CockpitGatewayPreset.matches(baseURL: candidate), "nonpreset rejected: " + (candidate ?? "nil"))
        }

        // Use actual disk-cache methods; restore any preexisting developer cache.
        let cacheURL = cacheFileURL
        let original = try? Data(contentsOf: cacheURL)
        let originalDate = (try? FileManager.default.attributesOfItem(atPath: cacheURL.path))?[.modificationDate] as? Date
        defer {
            cachedRegistry = nil; cacheTimestamp = nil; isRefreshing = false
            if let original {
                try? original.write(to: cacheURL, options: .atomic)
                if let originalDate { try? FileManager.default.setAttributes([.modificationDate: originalDate], ofItemAtPath: cacheURL.path) }
            } else { try? FileManager.default.removeItem(at: cacheURL) }
            URLProtocol.unregisterClass(CatalogHTTPFixture.self)
        }
        try? FileManager.default.removeItem(at: cacheURL)
        cachedRegistry = nil; cacheTimestamp = nil; isRefreshing = true
        let initial = loadRegistry()!
        check(initial.count == 224, "clean launch loads all 223 providers plus Cockpit")
        check(Set(initial["cockpit"]!.models.keys) == expected, "clean launch uses verified IDs")

        let upstream = Data(#"{"openai":{"id":"openai","name":"OpenAI","api":"https://api.openai.com/v1","models":{"gpt-6-sol":{"id":"gpt-6-sol","name":"upstream","reasoning":false,"limit":{"context":1234},"cost":{"input":9,"output":19},"release_date":"2026-01-02","reasoning_options":[{"type":"effort","values":["low"]}]}}},"llama":{"id":"llama","name":"Llama","api":"https://api.llama.com/compat/v1/","models":{"llama-real":{"id":"llama-real","limit":{"context":555}}}},"cockpit":{"id":"cockpit","api":"https://not-local.example/v1","models":{"invented":{"id":"invented"}}}}"#.utf8)
        let parsed = parseRegistry(upstream)!
        check(parsed.count == 3, "remote fixture merged, not replaced by entire bundle")
        check(parsed["openai"]!.models["gpt-6-sol"]!.limit?.context == 1234, "upstream provider remains untouched")
        check(parsed["llama"]!.models["llama-real"]!.limit?.context == 555, "second upstream provider remains untouched")
        check(parsed["cockpit"]!.api == CockpitGatewayPreset.lanBaseURL, "remote cannot overwrite local gateway address")
        check(Set(parsed["cockpit"]!.models.keys) == expected, "remote cannot inject a fabricated gateway model")
        check(parseRegistry(Data("broken JSON".utf8)) == nil, "malformed JSON fails without replacing cache")

        saveDiskCache(upstream)
        cachedRegistry = nil; cacheTimestamp = nil
        let fromDisk = loadRegistry()!
        check(fromDisk.count == 3 && Set(fromDisk["cockpit"]!.models.keys) == expected,
              "existing downloaded disk cache always receives local overlay")
        for base in [CockpitGatewayPreset.lanBaseURL, CockpitGatewayPreset.tailscaleBaseURL] {
            let models = fetchModels(forBaseURL: base)
            check(Set(models.map(\.id)) == expected, "both gateway aliases resolve all three models")
            check(models.allSatisfy { $0.contextWindow == 272000 && $0.maxOutputTokens == nil },
                  "known context retained, unknown output remains nil")
            check(models.allSatisfy { $0.effortDeclarationIsAuthoritative == true }, "gateway effort metadata is authoritative only for gateway")
        }
        for candidate in denied.compactMap({ $0 }) {
            check(fetchModels(forBaseURL: candidate).isEmpty, "no hostname fallback to Cockpit: " + candidate)
        }
        check(fetchModels(forBaseURL: "https://api.llama.com/compat/v1").first?.id == "llama-real",
              "existing provider URL discovery still works")
        check(priceCatalog().filter { $0.provider == "cockpit" }.allSatisfy { $0.input == nil && $0.output == nil },
              "unknown gateway pricing stays unknown rather than zero")
        let stage2 = buildStage2Index(fromDisk)
        check(stage2[normalizedModelKey("gpt-6-sol")]?.model.limit?.context == 1234,
              "private metadata never changes another provider's capability vote")
        check(stage2[normalizedModelKey("gpt-6.1-sol")] == nil, "private-only ID absent from cross-provider index")
        let aggregate = buildAggregateIndex(fromDisk)
        check(aggregate[normalizedModelKey("gpt-6-sol")]?.limit?.context == 1234,
              "private metadata excluded from aggregate fallback")
        let enriched = enrichModel(LLMModel(id: "gpt-6-sol", displayName: "upstream", provider: "OpenAI"))
        check(enriched.contextWindow == 1234 && enriched.supportsReasoning == false,
              "existing OpenAI capability inference remains upstream-owned")
        let cockpitModel = enrichModel(LLMModel(id: "gpt-6-sol", displayName: "Cockpit", provider: "Cockpit"))
        check(cockpitModel.contextWindow == 272000 && cockpitModel.supportsReasoning == true,
              "Cockpit own-provider inference uses its verified metadata")

        var remoteKnown = LLMModel(id: "gpt-6-sol", displayName: "Real remote display",
            provider: "OpenAI", modalityOverride: [.imageInput, .textOutput],
            contextWindow: 999, maxOutputTokens: 321, supportsReasoning: false,
            interleavedReasoningField: "remote_field", reasoningEffortValues: ["low"],
            declaresNoEffortTiers: true)
        remoteKnown.voiceRole = "tts"
        remoteKnown.effortDeclarationIsAuthoritative = true
        var remoteNew = LLMModel(id: "new-gateway-model", displayName: "Actual future model",
            provider: "OpenAI", modalityOverride: [.audioOutput],
            contextWindow: 456, maxOutputTokens: 78, supportsReasoning: true,
            interleavedReasoningField: "future_field", reasoningEffortValues: ["high"],
            declaresNoEffortTiers: false)
        remoteNew.voiceRole = "stt"
        remoteNew.effortDeclarationIsAuthoritative = true
        let remote = [remoteKnown, remoteNew]
        check(cockpitModels(remote, forBaseURL: "https://api.openai.com/v1") == remote,
              "non-Cockpit discovery is byte-for-byte model-value equivalent")
        check(cockpitModels(remote, forBaseURL: nil) == remote,
              "missing endpoint does not relabel another provider")
        let own = cockpitModels(remote, forBaseURL: CockpitGatewayPreset.tailscaleBaseURL)
        check(own.map(\.id) == remote.map(\.id), "remote IDs and ordering retained without supplementing missing IDs")
        check(own.count == 2 && !own.contains { $0.id == "gpt-6.1-sol" },
              "catalog does not claim all three gateway models were returned")
        check(own[0].provider == "Cockpit" && own[0].contextWindow == 272000 && own[0].supportsReasoning == true,
              "known gateway model replaces public OpenAI capability metadata")
        check(own[0].reasoningEffortValues == ["low", "medium", "high", "xhigh", "max", "ultra"] &&
              own[0].effortDeclarationIsAuthoritative == true && own[0].declaresNoEffortTiers == false,
              "known model restores own efforts and removes contradictory public no-effort declaration")
        check(own[0].voiceRole == nil && own[0].maxOutputTokens == nil &&
              own[0].displayName == remoteKnown.displayName && own[0].interleavedReasoningField == nil,
              "known model retains remote display name but clears unknown public metadata")
        var expectedNew = remoteNew
        expectedNew = LLMModel(id: remoteNew.id, displayName: remoteNew.displayName, provider: "Cockpit",
            modalityOverride: remoteNew.modalityOverride, contextWindow: remoteNew.contextWindow,
            maxOutputTokens: remoteNew.maxOutputTokens, supportsReasoning: remoteNew.supportsReasoning,
            interleavedReasoningField: remoteNew.interleavedReasoningField,
            reasoningEffortValues: remoteNew.reasoningEffortValues,
            declaresNoEffortTiers: remoteNew.declaresNoEffortTiers)
        expectedNew.voiceRole = remoteNew.voiceRole
        expectedNew.effortDeclarationIsAuthoritative = nil
        check(own[1] == expectedNew, "future real ID keeps every other field, public effort authority cleared")
        check(cockpitModels([], forBaseURL: CockpitGatewayPreset.lanBaseURL).isEmpty,
              "empty real response stays empty; local catalog is not availability")

        // Exercise the real async refresh + disk persistence, intercepting only HTTP.
        CatalogHTTPFixture.data = upstream
        check(URLProtocol.registerClass(CatalogHTTPFixture.self), "HTTP test transport registered")
        let refreshed = await refreshFromNetwork()
        check(refreshed, "production async network refresh succeeded")
        check(cachedRegistry?.count == 3 && Set(cachedRegistry!["cockpit"]!.models.keys) == expected,
              "network refresh preserves local gateway and unrelated upstream entries")
        check(loadDiskCache()?.0 == upstream, "upstream disk cache content persists unmodified")
        cachedRegistry = nil; cacheTimestamp = nil; isRefreshing = true
        check(loadRegistry()?.count == 3 && Set(cachedRegistry!["cockpit"]!.models.keys) == expected,
              "restart after network refresh reapplies local overlay")
        check(releaseIndex()?.byFullId["gpt-6-sol"]?.context == 1234,
              "global release ranking still uses upstream model context")
        print("Production Cockpit catalog: \(checks) checks passed")
    }
}

@main struct CockpitCatalogRegression {
    static func main() async throws { try await ModelsDevAPI.runCockpitCatalogTests() }
}
'''


def native_source():
    llm = (ROOT / "src/ios/Providers/LLMTypes.swift").read_text(encoding="utf-8")
    # Include the real model data members/initializer, not its unrelated UI helpers.
    llm = llm.split("    // [T-anthropic-context-window]", 1)[0] + "\n}\n"
    ranking = (ROOT / "src/ios/Providers/ModelReleaseIndex.swift").read_text(encoding="utf-8")
    ranking = ranking.replace('private let logger = AppLogger(category: "ModelReleaseIndex")', "")
    return SOURCE.read_text(encoding="utf-8") + "\n" + llm + "\n" + ranking + "\n" + SWIFT_TEST


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-swift", action="store_true")
    parser.add_argument("--emit-swift", type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CatalogContracts)
    if not unittest.TextTestRunner().run(suite).wasSuccessful():
        raise SystemExit(1)
    if args.emit_swift:
        args.emit_swift.parent.mkdir(parents=True, exist_ok=True)
        args.emit_swift.write_text(native_source(), encoding="utf-8")
        shutil.copyfile(CATALOG, args.emit_swift.parent / CATALOG.name)
        print("Emitted production Swift test harness:", args.emit_swift)
    swift = shutil.which("swiftc")
    if not swift:
        if args.require_swift:
            raise SystemExit("swiftc required; production Swift test not run")
        print("Production Swift Cockpit tests NOT RUN on this host (swiftc missing)")
    else:
        with tempfile.TemporaryDirectory(prefix="minis-cockpit-") as d:
            directory = Path(d)
            source = directory / "CockpitCatalogTests.swift"
            source.write_text(native_source(), encoding="utf-8")
            shutil.copyfile(CATALOG, directory / CATALOG.name)
            exe = directory / "cockpit-catalog-tests"
            subprocess.run([swift, "-swift-version", "5", "-parse-as-library", str(source), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=60)
