"""Endpoint-scoped OpenAI API-key model cache regression.

Runs extracted production Swift fetch/cache methods with fixture network/model/logger
and an isolated storage root. OAuth discovery is deliberately not exercised/changed.
"""
import argparse
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
import os

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / 'src/ios/Providers/OpenAI/OpenAIModelsAPI.swift'
SOURCE = SOURCE_PATH.read_text(encoding='utf-8')


def declaration(text, marker):
    start = text.index(marker)
    brace = text.index('{', start)
    depth = 1
    pos = brace + 1
    while depth:
        depth += (text[pos] == '{') - (text[pos] == '}')
        pos += 1
    return text[start:pos]


FETCH = declaration(SOURCE, 'static func fetchModels(apiKey:')
STRIP = declaration(SOURCE, 'private func stripV1Suffix(')
KEY = declaration(SOURCE, 'private struct APIKeyModelsCacheKey:')
CACHE = declaration(SOURCE, 'private enum OpenAIModelsCache {')


class Contracts(unittest.TestCase):
    def test_endpoint_resolved_before_cache_lookup(self):
        self.assertLess(FETCH.index('URLBuilding.join('), FETCH.index('OpenAIModelsCache.load(key:'))
        for part in ('endpoint: url.absoluteString', 'apiKey: apiKey', 'userAgent: userAgent',
                     'filterOpenAIOnly: !isCustomBase'):
            self.assertIn(part, FETCH)
        self.assertIn('if !forceRefresh,', FETCH)
        self.assertIn('OpenAIModelsCache.save(models, key: cacheKey)', FETCH)
        self.assertNotIn('credential: apiKey', FETCH)

    def test_typed_key_and_no_plaintext_cache_identity(self):
        self.assertIn(': Hashable, Codable', KEY)
        for field in ('endpoint: String', 'apiKey: String', 'userAgent: String?', 'filterOpenAIOnly: Bool'):
            self.assertIn(field, KEY)
        self.assertIn('encoder.outputFormatting = [.sortedKeys]', CACHE)
        self.assertIn('SHA256.hash(data: data)', CACHE)
        self.assertIn('"api-key-v2-" + digest', CACHE)
        self.assertNotIn('encoder.encode(key)', declaration(CACHE, 'private static func save(_ models:'))
        for line in FETCH.splitlines():
            if 'logger.' in line:
                self.assertNotIn('\\(apiKey)', line)
                self.assertNotIn('\\(cacheKey)', line)

    def test_oauth_keeps_separate_existing_credential_path(self):
        oauth = declaration(SOURCE, 'static func fetchModelsOAuth(')
        self.assertNotIn('APIKeyModelsCacheKey', oauth)
        self.assertIn('OpenAIModelsCache.load(credential: cacheKey)', oauth)
        self.assertIn('OpenAIModelsCache.save(models, credential: cacheKey)', oauth)
        self.assertIn('SHA256.hash(data: Data(credential.utf8))', CACHE)


HARNESS = r'''
import Foundation
import CryptoKit
struct LLMModel: Codable, Equatable { let id: String }
enum LLMError: Error { case providerError(message: String) }
struct FixtureLogger { func info(_ message: String) {} }
private let logger = FixtureLogger()
__STRIP__
__KEY__
__CACHE__
enum OpenAIModelsAPI {
    private static let defaultBaseURL = "https://api.openai.com"
    static var requests: [URLRequest] = []
    __FETCH__
    private static func performFetch(_ request: URLRequest, filterOpenAIOnly: Bool) async throws -> [LLMModel] {
        requests.append(request)
        return [LLMModel(id: "fixture-\(requests.count)-\(filterOpenAIOnly)")]
    }
}
@main struct Test {
    static func main() async throws {
        let key = "fixture-same-key-not-a-secret"
        let defaultModels = try await OpenAIModelsAPI.fetchModels(apiKey: key)
        precondition(OpenAIModelsAPI.requests.count == 1)
        let defaultAgain = try await OpenAIModelsAPI.fetchModels(apiKey: key)
        precondition(defaultAgain == defaultModels && OpenAIModelsAPI.requests.count == 1)
        let host = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-one.test:61722/v1")
        precondition(host != defaultModels && OpenAIModelsAPI.requests.count == 2)
        let hostAgain = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-one.test:61722/v1/")
        precondition(hostAgain == host && OpenAIModelsAPI.requests.count == 2)
        let otherHost = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-two.test:61722/v1")
        precondition(otherHost != host && OpenAIModelsAPI.requests.count == 3)
        let port = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-one.test:61723/v1")
        precondition(port != host && OpenAIModelsAPI.requests.count == 4)
        let path = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-one.test:61722/custom/v1")
        precondition(path != host && OpenAIModelsAPI.requests.count == 5)
        let otherKey = try await OpenAIModelsAPI.fetchModels(apiKey: key + "-other", baseURL: "http://host-one.test:61722/v1")
        precondition(otherKey != host && OpenAIModelsAPI.requests.count == 6)
        let ua = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-one.test:61722/v1", userAgent: "fixture-one")
        let uaOther = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-one.test:61722/v1", userAgent: "fixture-two")
        precondition(ua != uaOther && OpenAIModelsAPI.requests.count == 8)
        let uaAgain = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-one.test:61722/v1", userAgent: "fixture-one")
        precondition(uaAgain == ua && OpenAIModelsAPI.requests.count == 8)
        let explicitDefault = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "https://api.openai.com")
        precondition(explicitDefault != defaultModels && OpenAIModelsAPI.requests.count == 9)
        let defaultStill = try await OpenAIModelsAPI.fetchModels(apiKey: key)
        precondition(defaultStill == defaultModels && OpenAIModelsAPI.requests.count == 9)
        let refreshed = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-one.test:61722/v1", forceRefresh: true)
        precondition(refreshed != host && OpenAIModelsAPI.requests.count == 10)
        let refreshedAgain = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-one.test:61722/v1", appendV1Suffix: false)
        precondition(refreshedAgain == refreshed && OpenAIModelsAPI.requests.count == 10)
        let hostUnchanged = try await OpenAIModelsAPI.fetchModels(apiKey: key, baseURL: "http://host-two.test:61722/v1")
        precondition(hostUnchanged == otherHost && OpenAIModelsAPI.requests.count == 10)
        precondition(OpenAIModelsAPI.requests[1].url?.absoluteString == "http://host-one.test:61722/v1/models")
        precondition(OpenAIModelsAPI.requests[6].value(forHTTPHeaderField: "User-Agent") == "fixture-one")
        let cache = URL(fileURLWithPath: ProcessInfo.processInfo.environment["MINIS_MODEL_CACHE_TEST_DIR"]!)
        let files = try FileManager.default.contentsOfDirectory(at: cache, includingPropertiesForKeys: nil)
        precondition(!files.isEmpty)
        for file in files {
            precondition(file.lastPathComponent.range(of: #"^api-key-v2-[a-f0-9]{64}\.json$"#, options: .regularExpression) != nil)
            let data = try Data(contentsOf: file)
            precondition(!String(decoding: data, as: UTF8.self).contains(key))
        }
        print("Production OpenAI API-key cache: 20 isolation/cache/refresh/privacy assertions PASSED")
    }
}
'''


def run_swift(required):
    swiftc = shutil.which('swiftc')
    if not swiftc:
        if required:
            raise SystemExit('swiftc required for production API-key cache regression')
        print('Production Swift OpenAI cache checks NOT RUN: swiftc unavailable')
        return
    # Inject only the disk root, not cache key/hash/load/save behavior.
    original_root = ('FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]\n'
                     '            .appendingPathComponent("com.minisre.app.openai-models-cache", isDirectory: true)')
    assert original_root in CACHE
    cache = CACHE.replace(original_root, 'URL(fileURLWithPath: ProcessInfo.processInfo.environment["MINIS_MODEL_CACHE_TEST_DIR"]!, isDirectory: true)')
    fixture = HARNESS.replace('__STRIP__', STRIP).replace('__KEY__', KEY).replace('__CACHE__', cache).replace('__FETCH__', FETCH)
    with tempfile.TemporaryDirectory(prefix='minis-openai-cache-') as directory:
        folder = pathlib.Path(directory)
        source = folder / 'fixture.swift'
        binary = folder / 'fixture'
        source.write_text(fixture, encoding='utf-8')
        subprocess.run([swiftc, '-parse-as-library', str(ROOT/'src/ios/Providers/URLBuilding.swift'),
                        str(source), '-o', str(binary)], check=True)
        env = dict(os.environ, MINIS_MODEL_CACHE_TEST_DIR=str(folder/'cache'))
        subprocess.run([str(binary)], env=env, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-swift', action='store_true')
    args = parser.parse_args()
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Contracts))
    if not result.wasSuccessful():
        raise SystemExit(1)
    run_swift(args.require_swift)
