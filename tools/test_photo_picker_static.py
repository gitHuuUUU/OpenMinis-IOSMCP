"""Source contracts only: UIKit presentation and latency still need an iOS device."""
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'src/ios/Agent/ISH/PhotoPickerBridge.swift').read_text(encoding='utf-8')

class PhotoPickerContracts(unittest.TestCase):
    def test_configuration_is_lazy(self):
        modifier = SOURCE.split('extension View {', 1)[1]
        self.assertNotIn('PHPickerConfiguration(', modifier)
        self.assertNotIn('.shared()', modifier)
        self.assertEqual(SOURCE.count('PHPickerConfiguration('), 1)
        self.assertIn('config.preferredAssetRepresentationMode = .current', SOURCE)

    def test_nonblocking_selected_asset_lookup(self):
        loading = SOURCE.index('loadingQueue.async {')
        lookup = SOURCE.index('PHAsset.fetchAssets(')
        provider = SOURCE.index('provider.loadFileRepresentation(')
        self.assertLess(loading, lookup)
        self.assertLess(lookup, provider)
        self.assertIn('results.compactMap(\\.assetIdentifier)', SOURCE)
        self.assertNotIn('PHAsset.fetchAssets(with:', SOURCE)
        self.assertEqual(SOURCE.count('PHAsset.fetchAssets('), 1)

    def test_presentation_lifecycle_and_bounded_transition_retry(self):
        self.assertIn('override func viewDidAppear', SOURCE)
        self.assertIn('presenter.transitionCoordinator == nil', SOURCE)
        self.assertIn('if attempt < 30', SOURCE)
        self.assertIn('presentationRetry?.cancel()', SOURCE)
        self.assertIn('coordinator.hostingVC = nil', SOURCE)
        self.assertLess(SOURCE.index('guard let presenter = top'), SOURCE.index('self.hosted = true'))

    def test_dismiss_cancel_and_completion_callback(self):
        self.assertIn('picker.dismiss(animated: true) { [weak self] in', SOURCE)
        self.assertIn('guard !results.isEmpty else {\n                onPicked([])', SOURCE)
        self.assertIn('group.notify(queue: .main)', SOURCE)
        self.assertIn('let onPicked = parent.onPicked', SOURCE)
        self.assertIn('assets.sorted { $0.0 < $1.0 }', SOURCE)

    def test_limits_and_media_support_preserved(self):
        self.assertIn('config.selectionLimit = max(1, self.parent.maxSelectionCount)', SOURCE)
        self.assertIn('.any(of: [.images, .videos])', SOURCE)
        self.assertIn('provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier)', SOURCE)
        self.assertIn('provider.loadFileRepresentation(forTypeIdentifier: UTType.movie.identifier)', SOURCE)

    def test_failed_copy_is_not_returned(self):
        copy = SOURCE.index('do { try FileManager.default.copyItem(at: url, to: tmp) }')
        failure = SOURCE.index('catch { return }', copy)
        publish = SOURCE.index('assets.append((index,PickedAsset(id: id, isVideo: true', failure)
        self.assertLess(copy, failure)
        self.assertLess(failure, publish)
        self.assertNotIn('try? FileManager.default.copyItem', SOURCE)
        self.assertIn('url.pathExtension.isEmpty ? "mov" : url.pathExtension', SOURCE)

if __name__ == '__main__':
    unittest.main()
