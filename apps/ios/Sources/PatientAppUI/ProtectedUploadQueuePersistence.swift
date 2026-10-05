import Foundation
import PatientAppDomain

/// Session-scoped encrypted queue metadata. Payload bytes remain attached only
/// in memory; the protected cache stores retry metadata and snapshots.
public actor ProtectedUploadQueuePersistence: UploadQueuePersistence {
    private let cache: any ProtectedCache
    private let sessionStore: any SessionStore
    private let key = "upload-queue-v1"
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(cache: any ProtectedCache, sessionStore: any SessionStore) {
        self.cache = cache
        self.sessionStore = sessionStore
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    public func load() async throws -> [PersistedUploadQueueItem] {
        guard let session = await sessionStore.currentSession(),
              let data = await cache.data(forKey: key, session: session) else { return [] }
        return try decoder.decode([PersistedUploadQueueItem].self, from: data)
    }

    public func save(_ items: [PersistedUploadQueueItem]) async throws {
        guard let session = await sessionStore.currentSession() else { return }
        let data = try encoder.encode(items)
        await cache.setData(data, forKey: key, session: session)
    }
}
