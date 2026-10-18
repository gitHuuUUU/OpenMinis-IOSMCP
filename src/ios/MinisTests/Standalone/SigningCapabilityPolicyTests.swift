// Foundation-only: swiftc Shared/SigningCapabilityPolicy.swift
//   MinisTests/Standalone/SigningCapabilityPolicyTests.swift -o /tmp/signing-policy-test
// /tmp/signing-policy-test
import Foundation

@main
struct SigningCapabilityPolicyTests {
    static func expect(_ condition: @autoclosure () -> Bool, _ label: String) {
        guard condition() else { fatalError("Signing capability policy failed: \(label)") }
    }

    static func main() {
        let empty: [String: Any] = [:]
        expect(!SigningCapabilityPolicy.allowsMinisCloudKit(empty), "empty CloudKit")
        expect(!SigningCapabilityPolicy.allowsOutsideAppContainer(empty), "empty cross-container")

        let serviceOnly: [String: Any] = ["com.apple.developer.icloud-services": ["CloudKit"]]
        expect(!SigningCapabilityPolicy.allowsMinisCloudKit(serviceOnly), "service without container")
        let containerOnly: [String: Any] = ["com.apple.developer.icloud-container-identifiers": ["iCloud.com.minisre.app"]]
        expect(!SigningCapabilityPolicy.allowsMinisCloudKit(containerOnly), "container without service")
        let wrongContainer: [String: Any] = [
            "com.apple.developer.icloud-services": ["CloudKit"],
            "com.apple.developer.icloud-container-identifiers": ["iCloud.other.app"],
        ]
        expect(!SigningCapabilityPolicy.allowsMinisCloudKit(wrongContainer), "wrong container")
        let validCloud: [String: Any] = [
            "com.apple.developer.icloud-services": ["CloudKit"],
            "com.apple.developer.icloud-container-identifiers": ["iCloud.com.minisre.app"],
        ]
        expect(SigningCapabilityPolicy.allowsMinisCloudKit(validCloud), "valid CloudKit")

        let platformOnly: [String: Any] = ["platform-application": true]
        expect(!SigningCapabilityPolicy.allowsOutsideAppContainer(platformOnly), "platform only")
        let sandboxOnly: [String: Any] = ["com.apple.private.security.no-sandbox": true]
        expect(!SigningCapabilityPolicy.allowsOutsideAppContainer(sandboxOnly), "no-sandbox only")
        let fullAccess: [String: Any] = [
            "platform-application": true,
            "com.apple.private.security.no-sandbox": true,
        ]
        expect(SigningCapabilityPolicy.allowsOutsideAppContainer(fullAccess), "both capabilities")
        let falseAccess: [String: Any] = [
            "platform-application": false,
            "com.apple.private.security.no-sandbox": true,
        ]
        expect(!SigningCapabilityPolicy.allowsOutsideAppContainer(falseAccess), "explicit false")
        print("Signing capability policy: 9 checks passed")
    }
}
