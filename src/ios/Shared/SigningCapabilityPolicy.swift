import Foundation

/// Pure decisions over the effective entitlements returned by the OS.
/// Kept separate from the runtime probe so Foundation-only tests can exercise it.
enum SigningCapabilityPolicy {
    static func allowsMinisCloudKit(_ entitlements: [String: Any]) -> Bool {
        let services = entitlements["com.apple.developer.icloud-services"] as? [String] ?? []
        let containers = entitlements["com.apple.developer.icloud-container-identifiers"] as? [String] ?? []
        return services.contains("CloudKit") && containers.contains("iCloud.com.minisre.app")
    }

    static func allowsOutsideAppContainer(_ entitlements: [String: Any]) -> Bool {
        (entitlements["platform-application"] as? Bool) == true &&
        (entitlements["com.apple.private.security.no-sandbox"] as? Bool) == true
    }
}
