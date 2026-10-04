import Foundation

/// A document and its traceable facts retained for offline viewing. The raw
/// upload bytes are intentionally absent; callers may cache metadata and
/// review results without persisting the original file.
public struct OfflineDocumentCacheEntry: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let document: Document
    public let facts: [Fact]
    public let cachedAt: Date

    public var id: UUID { document.id }

    public init(document: Document, facts: [Fact] = [], cachedAt: Date) {
        self.document = document
        self.facts = facts
        self.cachedAt = cachedAt
    }
}

public enum OfflineDocumentCacheRead: Equatable, Sendable {
    case missing
    case fresh(OfflineDocumentCacheEntry)
    case stale(OfflineDocumentCacheEntry)

    public var entry: OfflineDocumentCacheEntry? {
        switch self {
        case .missing: nil
        case let .fresh(entry), let .stale(entry): entry
        }
    }

    public var isStale: Bool {
        if case .stale = self { true } else { false }
    }
}

/// Provider-neutral local document cache. Implementations can use an encrypted
/// database or protected storage on iOS; tests use the actor-backed memory store.
public protocol OfflineDocumentCacheStore: Sendable {
    func read(documentID: UUID, now: Date, maxAge: Duration) async -> OfflineDocumentCacheRead
    func write(_ entry: OfflineDocumentCacheEntry) async
    func remove(documentID: UUID) async
    func removeAll() async
}

public actor InMemoryOfflineDocumentCacheStore: OfflineDocumentCacheStore {
    private var entries: [UUID: OfflineDocumentCacheEntry] = [:]

    public init() {}

    public func read(documentID: UUID, now: Date, maxAge: Duration) async -> OfflineDocumentCacheRead {
        guard let entry = entries[documentID] else { return .missing }
        let age = max(0, now.timeIntervalSince(entry.cachedAt))
        return age > maxAge.timeInterval ? .stale(entry) : .fresh(entry)
    }

    public func write(_ entry: OfflineDocumentCacheEntry) async {
        entries[entry.document.id] = entry
    }

    public func remove(documentID: UUID) async {
        entries.removeValue(forKey: documentID)
    }

    public func removeAll() async {
        entries.removeAll(keepingCapacity: false)
    }
}

private extension Duration {
    var timeInterval: TimeInterval {
        let components = self.components
        let seconds = Double(components.seconds)
        let attoseconds = Double(components.attoseconds) / 1_000_000_000_000_000_000
        return max(0, seconds + attoseconds)
    }
}

