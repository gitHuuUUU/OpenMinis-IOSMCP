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
    let configuration: PHPickerConfiguration
    let onPicked: ([PickedAsset]) -> Void

    func makeUIViewController(context: Context) -> UIViewController {
        let host = UIViewController()
        host.view.frame = .zero
        return host
    }

    func updateUIViewController(_ uiViewController: UIViewController, context: Context) {
        context.coordinator.parent=self
        guard isPresented, !context.coordinator.hosted else { return }
        // A request must not be consumed until a visible presenter exists.
        DispatchQueue.main.async { [weak uiViewController] in
            guard let host=uiViewController, self.isPresented, !context.coordinator.hosted,
                  let window=host.view.window else { return }
            var top=window.rootViewController
            while let next=top?.presentedViewController { top=next }
            guard let presenter=top, !presenter.isBeingDismissed else { return }
            let picker=PHPickerViewController(configuration:self.configuration)
            picker.delegate=context.coordinator
            context.coordinator.hosted=true
            context.coordinator.hostingVC=host
            presenter.present(picker,animated:true)
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        var parent: PhotoPickerPresenter
        var hosted = false
        weak var hostingVC: UIViewController?

        init(_ parent: PhotoPickerPresenter) {
            self.parent = parent
        }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            // Always dismiss, even on cancel.
            picker.dismiss(animated: true)
            parent.isPresented = false
            hosted = false

            let providers = results.map(\.itemProvider)
            guard !providers.isEmpty else {
                parent.onPicked([])
                return
            }

            var assets: [(Int,PickedAsset)] = []
            let lock = NSLock()
            let group = DispatchGroup()

            for (index,pair) in zip(providers, results).enumerated() {
                let (provider,result)=pair
                let id = UUID()
                let isVideo = provider.hasItemConformingToTypeIdentifier(UTType.movie.identifier)
                // Preserve the original photo's creation date (via its PHAsset
                // local identifier), mirroring the PhotosPicker path.
                var assetDate: Date?
                if [.authorized,.limited].contains(PHPhotoLibrary.authorizationStatus(for:.readWrite)),
                   let assetID = result.assetIdentifier,
                   let asset = PHAsset.fetchAssets(withLocalIdentifiers: [assetID], options: nil).firstObject {
                    assetDate = asset.creationDate
                }

                group.enter()
                if isVideo {
                    provider.loadFileRepresentation(forTypeIdentifier: UTType.movie.identifier) { url, _ in
                        defer { group.leave() }
                        guard let url else { return }
                        let tmp = FileManager.default.temporaryDirectory
                            .appendingPathComponent("iosmcp-pick-\(id.uuidString).mov")
                        try? FileManager.default.copyItem(at: url, to: tmp)
                        let ext = provider.registeredTypeIdentifiers
                            .compactMap { UTType($0)?.preferredFilenameExtension }
                            .first
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
                self.parent.onPicked(ordered)
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
        var config = PHPickerConfiguration(photoLibrary: .shared())
        config.selectionLimit = maxSelectionCount
        config.filter = matchingImagesOnly ? .images : .any(of: [.images, .videos])
        return background(
            PhotoPickerPresenter(isPresented: isPresented,
                                 configuration: config,
                                 onPicked: onPicked)
                .frame(width: 0, height: 0)
        )
    }
}
