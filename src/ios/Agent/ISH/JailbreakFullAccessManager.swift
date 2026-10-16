//
//  JailbreakFullAccessManager.swift
//  MinisApp
//
//  [IOS-MCP] Full-access bridge for jailbroken devices.
//
//  When installed via TrollStore on a jailbroken iPhone (platform-application
//  + com.apple.private.security.no-container entitlements), the app is not
//  sandboxed to its own container: the REAL iOS filesystem is reachable. This
//  manager exposes that filesystem inside the iSH guest so the agent (and the
//  user's terminal) operates with root semantics over the whole device:
//
//    /ios       <- real "/"      (read-only; whole system visible)
//    /var/ios   <- real "/var"   (read-write; the writable core)
//    /usr/ios   <- real "/usr"   (read-only; toolchain & system binaries)
//
//  The guest rootfs itself runs as uid 0, so commands inside iSH already run
//  as root within the sandbox; the mounted trees give that root real access
//  to the device outside the app container.
//

import Foundation
import SQLite3

final class JailbreakFullAccessManager {
    static let shared = JailbreakFullAccessManager()
    private var enabled = false
    private let logger = AppLogger(category: "JailbreakFullAccess")

    private init() {}

    /// Detect a jailbroken filesystem. Rootless jailbreaks (Dopamine /
    /// palera1n-rootless) expose /var/jb; rootful ones leave Cydia / unc0ver
    /// markers. TrollStore alone does NOT mean jailbroken — this checks the
    /// filesystem, not the installer.
    var isJailbroken: Bool {
        let fm = FileManager.default
        if fm.fileExists(atPath: "/var/jb") { return true }
        if fm.fileExists(atPath: "/usr/libexec/cydia") { return true }
        if fm.fileExists(atPath: "/.installed_unc0ver") { return true }
        return false
    }

    /// Bind the real iOS filesystem into the guest. Idempotent; no-ops on
    /// stock (non-jailbroken) devices or before the kernel has booted.
    func enableIfJailbroken() {
        guard isJailbroken, !enabled, ISHKernel.shared.isBooted else { return }
        enabled = true

        // Ensure the guest mount points exist in meta.db before binding.
        ensureFakefsDir("/ios")
        ensureFakefsDir("/var/ios")
        ensureFakefsDir("/usr/ios")

        let kernel = ISHKernel.shared

        let roSys = kernel.bindMountPath("/ios", toHostPath: "/", readOnly: true)
        logger.info("JB: bind / -> /ios  rc=\(roSys)")

        let rwVar = kernel.bindMountPath("/var/ios", toHostPath: "/var", readOnly: false)
        logger.info("JB: bind /var -> /var/ios  rc=\(rwVar)")

        let roUsr = kernel.bindMountPath("/usr/ios", toHostPath: "/usr", readOnly: true)
        logger.info("JB: bind /usr -> /usr/ios  rc=\(roUsr)")

        logger.info("JB: full-access mounts applied (iOS \(UIDevice.current.systemVersion))")
    }

    // MARK: - meta.db helpers (mirrors AIChatViewModel.ensureFakefsMetadata)

    private static let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    private func bindPathBlob(_ stmt: OpaquePointer, index: Int32, path: String) {
        let utf8 = Array(path.utf8)
        sqlite3_bind_blob(stmt, index, utf8, Int32(utf8.count), Self.SQLITE_TRANSIENT)
    }

    /// Create the guest directory entry in fakefs meta.db so bind mounting
    /// into it can succeed.
    private func ensureFakefsDir(_ linuxPath: String) {
        let metaDBPath = RootfsManager.shared.rootfsPath.appendingPathComponent("meta.db").path
        var db: OpaquePointer?
        guard sqlite3_open_v2(metaDBPath, &db, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK,
              let db else { return }
        defer { sqlite3_close(db) }

        var check: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT inode FROM paths WHERE path = ?", -1, &check, nil) == SQLITE_OK,
              let check else { return }
        defer { sqlite3_finalize(check) }
        bindPathBlob(check, index: 1, path: linuxPath)
        if sqlite3_step(check) == SQLITE_ROW { return } // already present

        // S_IFDIR | 0755
        var statBytes: [UInt8] = Array(repeating: 0, count: 16)
        let mode: UInt32 = UInt32(0o040755).littleEndian
        withUnsafeBytes(of: mode) { src in
            for i in 0..<4 { statBytes[i] = src[i] }
        }

        var insStat: OpaquePointer?
        guard sqlite3_prepare_v2(db, "INSERT INTO stats (stat) VALUES (?)", -1, &insStat, nil) == SQLITE_OK,
              let insStat else { return }
        defer { sqlite3_finalize(insStat) }
        sqlite3_bind_blob(insStat, 1, statBytes, Int32(statBytes.count), Self.SQLITE_TRANSIENT)
        guard sqlite3_step(insStat) == SQLITE_DONE else { return }

        var insPath: OpaquePointer?
        guard sqlite3_prepare_v2(db, "INSERT OR REPLACE INTO paths (path, inode) VALUES (?, last_insert_rowid())", -1, &insPath, nil) == SQLITE_OK,
              let insPath else { return }
        defer { sqlite3_finalize(insPath) }
        bindPathBlob(insPath, index: 1, path: linuxPath)
        sqlite3_step(insPath)
    }
}
