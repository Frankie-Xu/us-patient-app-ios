import Foundation

#if canImport(Security)
import Security
#endif

/// Storage for the small, provider-neutral session record that identifies the
/// account currently active on the device. Tokens and provider credentials are
/// intentionally outside this boundary.
public protocol SessionCredentialStore: Sendable {
    func read() async -> SessionContext?
    func save(_ session: SessionContext) async
    func clear() async
}

/// A deterministic actor-backed session store used by unit tests and previews.
public actor InMemorySessionCredentialStore: SessionCredentialStore {
    private var session: SessionContext?

    public init(session: SessionContext? = nil) {
        self.session = session
    }

    public func read() async -> SessionContext? { session }

    public func save(_ session: SessionContext) async {
        self.session = session
    }

    public func clear() async {
        session = nil
    }
}

#if canImport(Security)

/// Keychain-backed implementation for iOS and other Apple platforms. The
/// record is deliberately limited to the account identifier and epoch; bearer
/// tokens remain owned by the authentication provider.
public final class KeychainSessionCredentialStore: SessionCredentialStore, @unchecked Sendable {
    private let service: String
    private let account: String

    public init(service: String = "com.patientapp.session", account: String = "active") {
        self.service = service
        self.account = account
    }

    public func read() async -> SessionContext? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else {
            return nil
        }
        return try? JSONDecoder().decode(SessionContext.self, from: data)
    }

    public func save(_ session: SessionContext) async {
        guard let data = try? JSONEncoder().encode(session) else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        ]
        if SecItemUpdate(query as CFDictionary, attributes as CFDictionary) != errSecSuccess {
            var insert = query
            attributes.forEach { insert[$0.key] = $0.value }
            _ = SecItemAdd(insert as CFDictionary, nil)
        }
    }

    public func clear() async {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        _ = SecItemDelete(query as CFDictionary)
    }
}

#else

/// Linux and non-Security builds retain the same injectable contract. This
/// fallback keeps package tests deterministic while Apple builds use Keychain.
public actor KeychainSessionCredentialStore: SessionCredentialStore {
    private var session: SessionContext?

    public init(service: String = "com.patientapp.session", account: String = "active") {}

    public func read() async -> SessionContext? { session }

    public func save(_ session: SessionContext) async {
        self.session = session
    }

    public func clear() async {
        session = nil
    }
}

#endif

public typealias InMemorySessionStorage = InMemorySessionCredentialStore
public typealias KeychainSessionStorage = KeychainSessionCredentialStore

/// Session lifecycle backed by an injectable credential store. Account changes
/// and logout invalidate all protected cache entries before publishing state.
public actor KeychainSessionStore: AuthSession {
    private let credentialStore: any SessionCredentialStore
    private let cache: any ProtectedCache
    private var activeSession: SessionContext?
    private var nextEpoch: Int
    private var state: AuthState = .signedOut
    private var didAttemptRestore = false

    public init(
        credentialStore: any SessionCredentialStore = KeychainSessionCredentialStore(),
        cache: any ProtectedCache = InMemoryProtectedCache()
    ) {
        self.credentialStore = credentialStore
        self.cache = cache
        self.nextEpoch = 0
    }

    public init(
        storage: any SessionCredentialStore,
        cache: any ProtectedCache = InMemoryProtectedCache()
    ) {
        self.init(credentialStore: storage, cache: cache)
    }

    public func currentSession() async -> SessionContext? {
        await restoreIfNeeded()
        return activeSession
    }

    public func authState() async -> AuthState {
        await restoreIfNeeded()
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

    public func restore() async -> AuthState {
        await restoreIfNeeded()
        return state
    }

    public func expire() async {
        await restoreIfNeeded()
        if activeSession != nil { nextEpoch += 1 }
        activeSession = nil
        await credentialStore.clear()
        await cache.purgeAll()
        state = .expired
    }

    public func beginSession(identifier: String) async -> SessionContext {
        await restoreIfNeeded()
        let normalized = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        if let activeSession, activeSession.identifier == normalized, !normalized.isEmpty {
            return activeSession
        }
        nextEpoch += 1
        let context = SessionContext(identifier: normalized, epoch: nextEpoch)
        await cache.purgeAll()
        await credentialStore.save(context)
        activeSession = context
        state = .signedIn(context)
        return context
    }

    public func logout() async {
        await restoreIfNeeded()
        nextEpoch += 1
        activeSession = nil
        await credentialStore.clear()
        await cache.purgeAll()
        state = .signedOut
    }

    public func isCurrent(_ session: SessionContext) async -> Bool {
        await restoreIfNeeded()
        return activeSession == session
    }

    private func restoreIfNeeded() async {
        guard !didAttemptRestore else { return }
        didAttemptRestore = true
        guard let persisted = await credentialStore.read() else { return }
        activeSession = persisted
        nextEpoch = max(nextEpoch, persisted.epoch)
        state = .signedIn(persisted)
    }
}

