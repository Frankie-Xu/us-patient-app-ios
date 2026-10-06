import Foundation

#if canImport(CryptoKit)
import CryptoKit
#endif

/// Versioned envelope stored by the offline metadata layer. Raw document bytes
/// are never accepted by this store; only Codable metadata and review facts are
/// sealed into the envelope.
public struct EncryptedMetadataEnvelope: Codable, Equatable, Hashable, Sendable {
    public let version: Int
    public let algorithm: String
    public let keyIdentifier: String
    public let nonce: Data
    public let ciphertext: Data
    public let tag: Data

    public init(
        version: Int = 1,
        algorithm: String,
        keyIdentifier: String,
        nonce: Data,
        ciphertext: Data,
        tag: Data
    ) {
        self.version = version
        self.algorithm = algorithm
        self.keyIdentifier = keyIdentifier
        self.nonce = nonce
        self.ciphertext = ciphertext
        self.tag = tag
    }
}

/// Provider-neutral byte storage. A production implementation can map this to
/// an encrypted database or protected file without changing the cache contract.
public protocol OfflineMetadataStorage: Sendable {
    func data(forKey key: String) async -> Data?
    func setData(_ data: Data, forKey key: String) async
    func remove(forKey key: String) async
    func removeAll() async
}

public actor InMemoryOfflineMetadataStorage: OfflineMetadataStorage {
    private var values: [String: Data] = [:]

    public init() {}

    public func data(forKey key: String) async -> Data? { values[key] }

    public func setData(_ data: Data, forKey key: String) async {
        values[key] = data
    }

    public func remove(forKey key: String) async {
        values.removeValue(forKey: key)
    }

    public func removeAll() async {
        values.removeAll(keepingCapacity: false)
    }
}

/// Platform-neutral crypto seam for offline metadata. Returning nil represents
/// a rejected envelope or unavailable key and is surfaced as a cache miss.
public protocol OfflineMetadataCipher: Sendable {
    func seal(_ plaintext: Data, associatedData: Data) -> EncryptedMetadataEnvelope?
    func open(_ envelope: EncryptedMetadataEnvelope, associatedData: Data) -> Data?
}

public typealias MetadataCipher = OfflineMetadataCipher

/// Deterministic test double. It is intentionally not a production cipher; use
/// CryptoKitOfflineMetadataCipher on Apple platforms for real at-rest privacy.
public struct DeterministicOfflineMetadataCipher: OfflineMetadataCipher {
    private let key: Data
    private let keyIdentifier: String

    public init(key: Data = Data("patient-app-test-key".utf8), keyIdentifier: String = "test-v1") {
        self.key = key
        self.keyIdentifier = keyIdentifier
    }

    public func seal(_ plaintext: Data, associatedData: Data) -> EncryptedMetadataEnvelope? {
        let nonce = Data(repeating: 0x5A, count: 12)
        let ciphertext = transform(plaintext, nonce: nonce, associatedData: associatedData)
        let tag = digest(plaintext, associatedData: associatedData)
        return EncryptedMetadataEnvelope(
            algorithm: "deterministic-test-xor",
            keyIdentifier: keyIdentifier,
            nonce: nonce,
            ciphertext: ciphertext,
            tag: tag
        )
    }

    public func open(_ envelope: EncryptedMetadataEnvelope, associatedData: Data) -> Data? {
        guard envelope.version == 1,
              envelope.algorithm == "deterministic-test-xor",
              envelope.keyIdentifier == keyIdentifier else { return nil }
        let plaintext = transform(envelope.ciphertext, nonce: envelope.nonce, associatedData: associatedData)
        return digest(plaintext, associatedData: associatedData) == envelope.tag ? plaintext : nil
    }

    private func transform(_ data: Data, nonce: Data, associatedData: Data) -> Data {
        let stream = Array(key) + Array(nonce) + Array(associatedData)
        guard !stream.isEmpty else { return data }
        return Data(data.enumerated().map { index, byte in
            byte ^ stream[index % stream.count] ^ UInt8(truncatingIfNeeded: index &* 31)
        })
    }

    private func digest(_ data: Data, associatedData: Data) -> Data {
        var hash: UInt64 = 14_695_981_039_346_656_037
        for byte in data + associatedData + key {
            hash ^= UInt64(byte)
            hash &*= 1_099_511_628_211
        }
        var bigEndian = hash.bigEndian
        return withUnsafeBytes(of: &bigEndian) { Data($0) }
    }
}

#if canImport(CryptoKit)

/// AES-GCM implementation used by iOS production wiring. The key identifier
/// allows rotation without changing the envelope or cache APIs.
public struct CryptoKitOfflineMetadataCipher: OfflineMetadataCipher {
    private let key: SymmetricKey
    private let keyIdentifier: String

    public init(key: Data, keyIdentifier: String = "aes-gcm-v1") {
        self.key = SymmetricKey(data: Data(SHA256.hash(data: key)))
        self.keyIdentifier = keyIdentifier
    }

    public func seal(_ plaintext: Data, associatedData: Data) -> EncryptedMetadataEnvelope? {
        do {
            let box = try AES.GCM.seal(plaintext, using: key, authenticating: associatedData)
            return EncryptedMetadataEnvelope(
                algorithm: "aes-256-gcm",
                keyIdentifier: keyIdentifier,
                nonce: Data(box.nonce),
                ciphertext: Data(box.ciphertext),
                tag: Data(box.tag)
            )
        } catch {
            return nil
        }
    }

    public func open(_ envelope: EncryptedMetadataEnvelope, associatedData: Data) -> Data? {
        guard envelope.version == 1,
              envelope.algorithm == "aes-256-gcm",
              envelope.keyIdentifier == keyIdentifier,
              let nonce = try? AES.GCM.Nonce(data: envelope.nonce),
              let box = try? AES.GCM.SealedBox(
                  nonce: nonce,
                  ciphertext: envelope.ciphertext,
                  tag: envelope.tag
              ) else { return nil }
        return try? AES.GCM.open(box, using: key, authenticating: associatedData)
    }
}

#else

/// Keeps Linux package builds source-compatible. Production iOS builds use the
/// CryptoKit implementation above; tests should inject the deterministic seam.
public struct CryptoKitOfflineMetadataCipher: OfflineMetadataCipher {
    public init(key: Data, keyIdentifier: String = "aes-gcm-v1") {}

    public func seal(_ plaintext: Data, associatedData: Data) -> EncryptedMetadataEnvelope? { nil }

    public func open(_ envelope: EncryptedMetadataEnvelope, associatedData: Data) -> Data? { nil }
}

#endif

/// Codable document cache that persists only encrypted metadata envelopes. It
/// also conforms to ProtectedCache so session logout/account switching can
/// purge the same encrypted backing store through the existing lifecycle seam.
public actor EncryptedOfflineDocumentCacheStore: OfflineDocumentCacheStore, ProtectedCache {
    private let storage: any OfflineMetadataStorage
    private let cipher: any OfflineMetadataCipher
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(
        storage: any OfflineMetadataStorage,
        cipher: any OfflineMetadataCipher,
        encoder: JSONEncoder = JSONEncoder(),
        decoder: JSONDecoder = JSONDecoder()
    ) {
        self.storage = storage
        self.cipher = cipher
        self.encoder = encoder
        self.decoder = decoder
        self.encoder.dateEncodingStrategy = .iso8601
        self.decoder.dateDecodingStrategy = .iso8601
    }

    public func read(documentID: UUID, now: Date, maxAge: Duration) async -> OfflineDocumentCacheRead {
        let key = documentKey(documentID)
        guard let entry = await decodeEntry(forKey: key) else { return .missing }
        let age = max(0, now.timeIntervalSince(entry.cachedAt))
        return age > maxAge.timeInterval ? .stale(entry) : .fresh(entry)
    }

    public func write(_ entry: OfflineDocumentCacheEntry) async {
        let key = documentKey(entry.document.id)
        guard let plaintext = try? encoder.encode(entry),
              let envelope = cipher.seal(plaintext, associatedData: Data(key.utf8)),
              let data = try? encoder.encode(envelope) else { return }
        await storage.setData(data, forKey: key)
    }

    public func remove(documentID: UUID) async {
        await storage.remove(forKey: documentKey(documentID))
    }

    public func removeAll() async {
        await storage.removeAll()
    }

    public func data(forKey key: String, session: SessionContext) async -> Data? {
        let storageKey = protectedKey(key, session: session)
        guard let envelopeData = await storage.data(forKey: storageKey),
              let envelope = try? decoder.decode(EncryptedMetadataEnvelope.self, from: envelopeData) else { return nil }
        return cipher.open(envelope, associatedData: Data(storageKey.utf8))
    }

    public func setData(_ data: Data, forKey key: String, session: SessionContext) async {
        let storageKey = protectedKey(key, session: session)
        guard let envelope = cipher.seal(data, associatedData: Data(storageKey.utf8)),
              let envelopeData = try? encoder.encode(envelope) else { return }
        await storage.setData(envelopeData, forKey: storageKey)
    }

    public func purge(session: SessionContext) async {
        // ProtectedCache intentionally exposes purge as an account boundary;
        // clearing the backing store avoids retaining another account's data.
        await storage.removeAll()
    }

    public func purgeAll() async {
        await storage.removeAll()
    }

    /// Exposes the persisted envelope for deterministic storage tests without
    /// exposing plaintext metadata through the production cache API.
    public func rawEnvelopeData(documentID: UUID) async -> Data? {
        await storage.data(forKey: documentKey(documentID))
    }

    private func decodeEntry(forKey key: String) async -> OfflineDocumentCacheEntry? {
        guard let data = await storage.data(forKey: key),
              let envelope = try? decoder.decode(EncryptedMetadataEnvelope.self, from: data),
              let plaintext = cipher.open(envelope, associatedData: Data(key.utf8)) else { return nil }
        return try? decoder.decode(OfflineDocumentCacheEntry.self, from: plaintext)
    }

    private func documentKey(_ id: UUID) -> String {
        "offline-document-v1:\(id.uuidString.lowercased())"
    }

    private func protectedKey(_ key: String, session: SessionContext) -> String {
        "protected-v1:\(session.identifier):\(session.epoch):\(key)"
    }
}

private extension Duration {
    var timeInterval: TimeInterval {
        let components = self.components
        return max(0, Double(components.seconds) + Double(components.attoseconds) / 1_000_000_000_000_000_000)
    }
}

