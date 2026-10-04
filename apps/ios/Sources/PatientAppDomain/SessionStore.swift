import Foundation

public struct SessionContext: Codable, Equatable, Hashable, Sendable {
    public let identifier: String
    public let epoch: Int

    public init(identifier: String, epoch: Int) {
        self.identifier = identifier
        self.epoch = epoch
    }
}

/// Provider-neutral boundary for protected, session-scoped bytes. Implementations
/// may later use Keychain/encrypted storage; this package ships memory only.
public protocol ProtectedCache: Sendable {
    func data(forKey key: String, session: SessionContext) async -> Data?
    func setData(_ data: Data, forKey key: String, session: SessionContext) async
    func purge(session: SessionContext) async
    func purgeAll() async
}

public actor InMemoryProtectedCache: ProtectedCache {
    private var values: [SessionContext: [String: Data]] = [:]

    public init() {}

    public func data(forKey key: String, session: SessionContext) async -> Data? {
        values[session]?[key]
    }

    public func setData(_ data: Data, forKey key: String, session: SessionContext) async {
        values[session, default: [:]][key] = data
    }

    public func purge(session: SessionContext) async {
        values.removeValue(forKey: session)
    }

    public func purgeAll() async {
        values.removeAll(keepingCapacity: false)
    }
}

/// Owns the active account identity and invalidates every previous epoch when
/// logging out or switching accounts.
public protocol SessionStore: Sendable {
    func currentSession() async -> SessionContext?
    func beginSession(identifier: String) async -> SessionContext
    func logout() async
    func isCurrent(_ session: SessionContext) async -> Bool
}

public actor InMemorySessionStore: SessionStore {
    private let cache: any ProtectedCache
    private var activeSession: SessionContext?
    private var nextEpoch = 0

    public init(cache: any ProtectedCache = InMemoryProtectedCache()) {
        self.cache = cache
    }

    public func currentSession() async -> SessionContext? { activeSession }

    public func beginSession(identifier: String) async -> SessionContext {
        let normalized = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        if let activeSession, activeSession.identifier == normalized, !normalized.isEmpty {
            return activeSession
        }
        nextEpoch += 1
        await cache.purgeAll()
        let context = SessionContext(identifier: normalized, epoch: nextEpoch)
        activeSession = context
        return context
    }

    public func logout() async {
        nextEpoch += 1
        activeSession = nil
        await cache.purgeAll()
    }

    public func isCurrent(_ session: SessionContext) async -> Bool {
        activeSession == session
    }
}
