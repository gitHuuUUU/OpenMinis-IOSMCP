import Foundation

@main struct StorageFallbackTests {
    static func main() throws {
        let fm = FileManager.default
        let library = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? fm.removeItem(at: library) }
        let fallback = SharedContainerStore.resolveStorageContainer(appGroupURL: nil, libraryURL: library)
        assert(fallback.lastPathComponent == "MinisLocalContainer")
        assert(fallback == SharedContainerStore.resolveStorageContainer(appGroupURL: nil, libraryURL: library))
        try fm.createDirectory(at: fallback, withIntermediateDirectories: true)
        let file = fallback.appendingPathComponent("persistent-test.txt")
        try Data("test".utf8).write(to: file)
        let recovered = try Data(contentsOf: file)
        assert(recovered == Data("test".utf8))
        let granted = library.appendingPathComponent("ExistingAppGroup", isDirectory: true)
        assert(SharedContainerStore.resolveStorageContainer(appGroupURL: granted, libraryURL: library) == granted)
        print("PASS: absent group fallback, stable path, file read/write, existing group preserved")
    }
}
