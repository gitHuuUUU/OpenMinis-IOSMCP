//
//  PhotoPickerBridge.swift
//  MinisApp
//
//  [IOS-MCP] PHPicker-based photo/video picking bridge (iOS 14+).
//
//  SwiftUI's PhotosPicker / PhotosPickerItem are iOS 16+; the app deploys
//  to iOS 15, so this bridge wraps the older PHPickerViewController and
//  delivers already-loaded assets back to SwiftUI through a closure.
//  Behaviour mirrors the PhotosPicker usage it replaces:
//    - up to `maxSelectionCount` items
//    - images come back as their original encoded bytes (Data), videos as
//      a temporary file URL
//

import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

/// A picked asset with its bytes (image) or temporary file (video) loaded.
struct PickedAsset {
    let id: UUID
    let isVideo: Bool
    let data: Data?          // images: original encoded bytes
    let videoURL: URL?       // videos: temporary file URL
    let ext: String?
    let date: Date?
}

/// Present `PHPickerViewController` from a SwiftUI context without relying
/// on iOS 16 PhotosPicker. Hosted via `.background(...)` so it does not
/// conflict with existing `.sheet` modifiers on the same view.
private struct PhotoPickerPresenter: UIViewControllerRepresentable {
    @Binding var isPresented: Bool
    let maxSelectionCount: Int
    let matchingImagesOnly: Bool
    let onPicked: ([PickedAsset]) -> Void

    // SwiftUI can update the representable before it has joined a window.
    final class HostController: UIViewController {
        var onReady: (() -> Void)?
        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            onReady?()
        }
    }

    func makeUIViewController(context: Context) -> HostController {
        let host = HostController()
        host.view.frame = .zero
        context.coordinator.hostingVC = host
        host.onReady = { [weak coordinator = context.coordinator] in
            coordinator?.requestPresentation()
        }
        return host
    }

    func updateUIViewController(_ host: HostController, context: Context) {
        context.coordinator.parent = self
        context.coordinator.requestPresentation()
    }

    static func dismantleUIViewController(_ host: HostController, coordinator: Coordinator) {
        host.onReady = nil
        coordinator.presentationRetry?.cancel()
        coordinator.hostingVC = nil
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        var parent: PhotoPickerPresenter
        var hosted = false
        weak var hostingVC: UIViewController?
        var presentationRetry: DispatchWorkItem?
        private let loadingQueue = DispatchQueue(label: "com.minisapp.photo-picker", qos: .userInitiated)

        init(_ parent: PhotoPickerPresenter) { self.parent = parent }

        func requestPresentation(attempt: Int = 0) {
            presentationRetry?.cancel()
            presentationRetry = nil
            guard parent.isPresented, !hosted, hostingVC != nil else { return }
            // Only one pending attempt; retry transient sheet transitions rather
            // than dropping a request before the presenter becomes visible.
            let work = DispatchWorkItem { [weak self] in
                guard let self, self.parent.isPresented, !self.hosted,
                      let host = self.hostingVC else { return }
                var top = host.view.window?.rootViewController
                while let next = top?.presentedViewController { top = next }
                guard let presenter = top, !presenter.isBeingDismissed,
                      !presenter.isBeingPresented, presenter.transitionCoordinator == nil else {
                    if attempt < 30 { self.requestPresentation(attempt: attempt + 1) }
                    return
                }
                // Build only on an actual open, never during SwiftUI body updates.
                var config = PHPickerConfiguration(photoLibrary: .shared())
                config.selectionLimit = max(1, self.parent.maxSelectionCount)
                config.filter = self.parent.matchingImagesOnly ? .images : .any(of: [.images, .videos])
                // Avoid a potentially expensive HEIC/video compatibility conversion.
                config.preferredAssetRepresentationMode = .current
                let picker = PHPickerViewController(configuration: config)
                picker.delegate = self
                self.hosted = true
                presenter.present(picker, animated: true)
            }
            presentationRetry = work
            DispatchQueue.main.asyncAfter(deadline: .now() + (attempt == 0 ? 0 : 0.1), execute: work)
        }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            // Keep hosted true until dismissal completes, including cancellation.
            parent.isPresented = false
            picker.dismiss(animated: true) { [weak self] in
                self?.hosted = false
                self?.requestPresentation()
            }
            let onPicked = parent.onPicked
            guard !results.isEmpty else {
                onPicked([])
                return
            }
            // PHAsset lookups and provider setup must not block the dismiss animation.
            loadingQueue.async {
                let providers = results.map(\.itemProvider)
                var dates: [String: Date] = [:]
                if [.authorized, .limited].contains(PHPhotoLibrary.authorizationStatus(for: .readWrite)) {
                    let identifiers = results.compactMap(\.assetIdentifier)
                    if !identifiers.isEmpty {
                        let fetched = PHAsset.fetchAssets(withLocalIdentifiers: identifiers, options: nil)
                        fetched.enumerateObjects { asset, _, _ in
                            if let date = asset.creationDate { dates[asset.localIdentifier] = date }
                        }
                    }
                }

                var assets: [(Int,PickedAsset)] = []
                let lock = NSLock()
                let group = DispatchGroup()

                for (index,pair) in zip(providers, results).enumerated() {
                    let (provider,result)=pair
                    let id = UUID()
                    let isVideo = provider.hasItemConformingToTypeIdentifier(UTType.movie.identifier)
                    let assetDate = result.assetIdentifier.flatMap { dates[$0] }

                    group.enter()
                    if isVideo {
                        provider.loadFileRepresentation(forTypeIdentifier: UTType.movie.identifier) { url, _ in
                            defer { group.leave() }
                            guard let url else { return }
                            let ext = url.pathExtension.isEmpty ? "mov" : url.pathExtension
                            let tmp = FileManager.default.temporaryDirectory
                                .appendingPathComponent("iosmcp-pick-\(id.uuidString).\(ext)")
                            // The provider URL expires when this callback returns.
                            // Publish only an actually copied file, never a phantom URL.
                            do { try FileManager.default.copyItem(at: url, to: tmp) }
                            catch { return }
                            lock.lock(); assets.append((index,PickedAsset(id: id, isVideo: true, data: nil, videoURL: tmp, ext: ext, date: assetDate))); lock.unlock()
                        }
                    } else {
                        provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, _ in
                            defer { group.leave() }
                            guard let data else { return }
                            let ext = provider.registeredTypeIdentifiers
                                .compactMap { UTType($0)?.preferredFilenameExtension }
                                .first
                            lock.lock(); assets.append((index,PickedAsset(id: id, isVideo: false, data: data, videoURL: nil, ext: ext, date: assetDate))); lock.unlock()
                        }
                    }
                }

                group.notify(queue: .main) {
                    // Stable order: insertion order of the providers.
                    let ordered = assets.sorted { $0.0 < $1.0 }.map { $0.1 }
                    onPicked(ordered)
                }
            }
        }
    }
}

extension View {
    /// [IOS-MCP] iOS 15-compatible photo/video picker (PHPicker under the
    /// hood). Mirrors `.photosPicker(isPresented:selection:maxSelectionCount:matching:)`.
    /// - Parameters:
    ///   - isPresented: whether to present the picker.
    ///   - maxSelectionCount: selection limit (1 for single-item callers).
    ///   - matchingImagesOnly: restrict to images (no videos).
    ///   - onPicked: called on the main queue with loaded assets (empty on cancel).
    func pickedPhotos(isPresented: Binding<Bool>,
                      maxSelectionCount: Int,
                      matchingImagesOnly: Bool = false,
                      onPicked: @escaping ([PickedAsset]) -> Void) -> some View {
        return background(
            PhotoPickerPresenter(isPresented: isPresented,
                                 maxSelectionCount: maxSelectionCount,
                                 matchingImagesOnly: matchingImagesOnly,
                                 onPicked: onPicked)
                .frame(width: 0, height: 0)
        )
    }
}
