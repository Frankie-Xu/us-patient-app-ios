import Foundation

public struct SessionContext: Codable, Equatable, Hashable, Sendable {
    public let identifier: String
    public let epoch: Int

    public init(identifier: String, epoch: Int) {
        self.identifier = identifier
        self.epoch = epoch
    }
}

/// Provider-neutral authentication lifecycle exposed to the app shell. The
/// memory implementation below intentionally carries no token or identity
/// provider state.
public enum AuthState: Equatable, Sendable {
    case signedOut
    case signedIn(SessionContext)
    case expired
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

/// Authentication lifecycle layered on top of the session epoch boundary.
/// Implementations may later connect to a provider without changing callers.
public protocol AuthSession: SessionStore {
    func authState() async -> AuthState
    func signIn(identifier: String) async -> AuthState
    func switchAccount(identifier: String) async -> AuthState
    func restore() async -> AuthState
    func expire() async
}

public actor InMemorySessionStore: AuthSession {
    private let cache: any ProtectedCache
    private var activeSession: SessionContext?
    private var nextEpoch = 0
    private var state: AuthState = .signedOut

    public init(cache: any ProtectedCache = InMemoryProtectedCache()) {
        self.cache = cache
    }

    public func currentSession() async -> SessionContext? { activeSession }

    public func authState() async -> AuthState { state }

    public func signIn(identifier: String) async -> AuthState {
        _ = await beginSession(identifier: identifier)
        return state
    }

    public func switchAccount(identifier: String) async -> AuthState {
        _ = await beginSession(identifier: identifier)
        return state
    }

    public func restore() async -> AuthState { state }

    public func expire() async {
        if activeSession != nil { nextEpoch += 1 }
        activeSession = nil
        await cache.purgeAll()
        state = .expired
    }

    public func beginSession(identifier: String) async -> SessionContext {
        let normalized = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        if let activeSession, activeSession.identifier == normalized, !normalized.isEmpty {
            return activeSession
        }
        nextEpoch += 1
        let epoch = nextEpoch
        await cache.purgeAll()
        let context = SessionContext(identifier: normalized, epoch: epoch)
        activeSession = context
        state = .signedIn(context)
        return context
    }

    public func logout() async {
        nextEpoch += 1
        activeSession = nil
        await cache.purgeAll()
        state = .signedOut
    }

    public func isCurrent(_ session: SessionContext) async -> Bool {
        activeSession == session
    }
}

/// Bridges an older SessionStore implementation into the authentication
/// boundary while preserving its purge and epoch behavior.
public actor SessionStoreAuthAdapter: AuthSession {
    private let store: any SessionStore
    private var state: AuthState = .signedOut

    public init(store: any SessionStore) { self.store = store }

    public func currentSession() async -> SessionContext? { await store.currentSession() }

    public func beginSession(identifier: String) async -> SessionContext {
        let context = await store.beginSession(identifier: identifier)
        state = .signedIn(context)
        return context
    }

    public func logout() async {
        await store.logout()
        state = .signedOut
    }

    public func isCurrent(_ session: SessionContext) async -> Bool {
        await store.isCurrent(session)
    }

    public func authState() async -> AuthState {
        if let current = await store.currentSession() { state = .signedIn(current) }
        return state
    }

    public func signIn(identifier: String) async -> AuthState {
        _ = await beginSession(identifier: identifier)
        return state
    }

    public func switchAccount(identifier: String) async -> AuthState {
        _ = await beginSession(identifier: identifier)
        return state
    }

    public func restore() async -> AuthState { await authState() }

    public func expire() async {
        await store.logout()
        state = .expired
    }
}
