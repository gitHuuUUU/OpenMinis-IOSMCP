import Foundation
import CoreFoundation
import Darwin

/// Read effective, kernel-visible entitlements rather than trusting a plist
/// shipped next to the app. A provisioning profile or re-signer can remove
/// capabilities requested by the project at build time.
enum AppSigningCapabilities {
    // SecTask functions are not declared by every iOS SDK. Resolve the public
    // Security symbols at runtime; failure means no optional capability.
    private typealias CreateSelf = @convention(c) (UnsafeRawPointer?) -> UnsafeMutableRawPointer?
    private typealias CopyValue = @convention(c) (
        UnsafeMutableRawPointer?, UnsafeRawPointer?, UnsafeMutableRawPointer?
    ) -> UnsafeMutableRawPointer?

    private static let effectiveEntitlements: [String: Any] = {
        guard let library = dlopen("/System/Library/Frameworks/Security.framework/Security", RTLD_LAZY) else { return [:] }
        defer { dlclose(library) }
        guard let createSymbol = dlsym(library, "SecTaskCreateFromSelf"),
              let copySymbol = dlsym(library, "SecTaskCopyValueForEntitlement") else { return [:] }
        let createSelf = unsafeBitCast(createSymbol, to: CreateSelf.self)
        let copyValue = unsafeBitCast(copySymbol, to: CopyValue.self)
        guard let task = createSelf(nil) else { return [:] }
        defer { Unmanaged<AnyObject>.fromOpaque(task).release() }

        var result: [String: Any] = [:]
        for key in ["com.apple.developer.icloud-services",
                    "com.apple.developer.icloud-container-identifiers",
                    "platform-application", "com.apple.private.security.no-sandbox"] {
            let cfKey = key as CFString
            guard let pointer = copyValue(task, Unmanaged.passUnretained(cfKey).toOpaque(), nil) else { continue }
            result[key] = Unmanaged<AnyObject>.fromOpaque(pointer).takeRetainedValue()
        }
        return result
    }()

    /// A local preflight only. It cannot prove that the named CloudKit
    /// container exists server-side, the account is signed in, or that later
    /// asynchronous framework calls will not raise an Objective-C exception.
    static var hasMinisCloudKit: Bool {
        SigningCapabilityPolicy.allowsMinisCloudKit(effectiveEntitlements)
    }

    /// Entitlements alone do not prove that a host path is readable or writable.
    /// The mount caller still has to check the host operation's return code.
    static var canAccessOutsideAppContainer: Bool {
        SigningCapabilityPolicy.allowsOutsideAppContainer(effectiveEntitlements)
    }
}

/// Reads and writes PendingShare data to the App Group shared container.
/// Compiled into both the main app target and the Share Extension target.
enum SharedContainerStore {
    static let appGroupID = "group.com.minisre.app"

    static var hasSharedAppGroupContainer: Bool {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupID) != nil
    }

    /// Resolve once per process. Missing App Group permissions must not trap
    /// during launch. The fallback is persistent Library storage, never tmp.
    static func resolveStorageContainer(appGroupURL: URL?, libraryURL: URL) -> URL {
        appGroupURL ?? libraryURL.appendingPathComponent("MinisLocalContainer", isDirectory: true)
    }

    static let storageContainerURL: URL = {
        let fm = FileManager.default
        let library = fm.urls(for: .libraryDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library", isDirectory: true)
        let url = resolveStorageContainer(
            appGroupURL: fm.containerURL(forSecurityApplicationGroupIdentifier: appGroupID),
            libraryURL: library)
        try? fm.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }()

    private static let pendingShareKey = "pendingShare"

    static var sharedDefaults: UserDefaults? {
        UserDefaults(suiteName: appGroupID)
    }

    /// Directory in the shared container for transferring attachment files.
    static var sharedFileDirectory: URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: appGroupID)?
            .appendingPathComponent("ShareExtension", isDirectory: true)
    }

    // MARK: - Write (called by Share Extension)

    static func savePendingShare(_ share: PendingShare) {
        guard let defaults = sharedDefaults else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(share) {
            defaults.set(data, forKey: pendingShareKey)
            defaults.synchronize()
        }
    }

    // MARK: - Read & Consume (called by main app)

    static func loadPendingShare() -> PendingShare? {
        guard let defaults = sharedDefaults,
              let data = defaults.data(forKey: pendingShareKey) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(PendingShare.self, from: data)
    }

    static func clearPendingShare() {
        sharedDefaults?.removeObject(forKey: pendingShareKey)
        sharedDefaults?.synchronize()
    }

    /// Remove all files from the shared transfer directory.
    static func cleanSharedFiles() {
        guard let dir = sharedFileDirectory else { return }
        let fm = FileManager.default
        if let files = try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) {
            for file in files {
                try? fm.removeItem(at: file)
            }
        }
    }
}
