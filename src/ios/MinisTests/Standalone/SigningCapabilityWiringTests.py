"""Static signing/startup wiring regression; run with python SigningCapabilityWiringTests.py.

This does not replace an iOS code-sign/build or device launch test.
"""

from pathlib import Path
import plistlib
import re
import unittest


IOS = Path(__file__).resolve().parents[2]


def source(relative):
    return (IOS / relative).read_text(encoding="utf-8")


class SigningCapabilityWiringTests(unittest.TestCase):
    def test_ordinary_signature_requests_no_special_capabilities(self):
        with (IOS / "OrdinarySigning.entitlements").open("rb") as stream:
            self.assertEqual(plistlib.load(stream), {})
        project = source("Minis.xcodeproj/project.pbxproj")
        settings = re.findall(r"CODE_SIGN_ENTITLEMENTS = ([^;]+);", project)
        self.assertEqual(settings, ["OrdinarySigning.entitlements"] * 8)

    def test_trollstore_profile_stays_separate(self):
        with (IOS / "TrollStore.entitlements").open("rb") as stream:
            entitlements = plistlib.load(stream)
        self.assertTrue(entitlements["platform-application"])
        self.assertTrue(entitlements["com.apple.private.security.no-sandbox"])
        self.assertIn("CloudKit", entitlements["com.apple.developer.icloud-services"])

    def test_launch_and_direct_sync_entries_probe_effective_entitlements(self):
        capabilities = source("Shared/SharedContainerStore.swift")
        self.assertIn('dlsym(library, "SecTaskCreateFromSelf")', capabilities)
        self.assertIn('dlsym(library, "SecTaskCopyValueForEntitlement")', capabilities)
        self.assertIn("SigningCapabilityPolicy.allowsMinisCloudKit", capabilities)
        self.assertIn("SigningCapabilityPolicy.allowsOutsideAppContainer", capabilities)
        self.assertIn("MinisLocalContainer", capabilities)
        for relative in (
            "MinisApp.swift",
            "Agent/Sync/CloudSyncEngine.swift",
            "Agent/Sync/V2/SyncV2Bootstrap.swift",
        ):
            self.assertIn("AppSigningCapabilities.hasMinisCloudKit", source(relative))
        self.assertIn("SharedContainerStore.hasSharedAppGroupContainer", source("MinisApp.swift"))
        provider = source("FileProvider/FileProviderExtension.swift")
        self.assertIn('library.appendingPathComponent("MinisLocalContainer"', provider)
        self.assertNotIn("forSecurityApplicationGroupIdentifier: \"group.com.minisre.app\"\n        )!", provider)

    def test_external_mount_requires_effective_capabilities(self):
        source_text = source("Agent/ISH/JailbreakFullAccessManager.swift")
        self.assertIn("guard isJailbroken, AppSigningCapabilities.canAccessOutsideAppContainer", source_text)


if __name__ == "__main__":
    unittest.main()
