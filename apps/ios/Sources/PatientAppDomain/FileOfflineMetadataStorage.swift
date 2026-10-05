import Foundation

/// File-backed encrypted metadata storage for app runtime use. Callers pass
/// only sealed envelopes; plaintext document bytes are never written here.
public actor FileOfflineMetadataStorage: OfflineMetadataStorage {
    private let directory: URL
    private let fileManager: FileManager

    public init(directory: URL? = nil, fileManager: FileManager = .default) {
        self.fileManager = fileManager
        let defaultDirectory = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
        self.directory = directory ?? defaultDirectory.appendingPathComponent("PatientApp/OfflineMetadata", isDirectory: true)
        try? fileManager.createDirectory(at: self.directory, withIntermediateDirectories: true)
    }

    public func data(forKey key: String) async -> Data? {
        try? Data(contentsOf: fileURL(forKey: key), options: [.mappedIfSafe])
    }

    public func setData(_ data: Data, forKey key: String) async {
        let url = fileURL(forKey: key)
        try? data.write(to: url, options: [.atomic, .completeFileProtectionUnlessOpen])
    }

    public func remove(forKey key: String) async {
        try? fileManager.removeItem(at: fileURL(forKey: key))
    }

    public func removeAll() async {
        guard let entries = try? fileManager.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) else { return }
        for entry in entries { try? fileManager.removeItem(at: entry) }
    }

    private func fileURL(forKey key: String) -> URL {
        // Base64URL keeps account identifiers and cache keys out of filenames
        // while remaining deterministic across launches.
        let encoded = Data(key.utf8).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        return directory.appendingPathComponent(encoded.isEmpty ? "empty" : encoded, isDirectory: false)
    }
}
