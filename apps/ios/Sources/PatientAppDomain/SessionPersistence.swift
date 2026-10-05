import Foundation

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

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

/// The short lived access token and rotating refresh token issued by the local
/// staging identity service. This record is persisted separately from the
/// account/epoch record so logging out can invalidate both independently.
public struct AuthTokenSet: Codable, Equatable, Sendable {
    public let accessToken: String
    public let refreshToken: String
    public let expiresAt: Date
    public let subject: String

    public init(accessToken: String, refreshToken: String, expiresAt: Date, subject: String) {
        self.accessToken = accessToken
        self.refreshToken = refreshToken
        self.expiresAt = expiresAt
        self.subject = subject
    }

    public var isExpired: Bool { expiresAt <= Date() }
    public var isExpiringSoon: Bool { expiresAt <= Date().addingTimeInterval(30) }
}

public enum AuthSessionError: Error, Equatable, Sendable {
    case invalidCredentials
    case invalidResponse
    case unavailable
    case configuration
}

public protocol AuthTokenStore: Sendable {
    func read() async -> AuthTokenSet?
    func save(_ tokens: AuthTokenSet) async
    func clear() async
}

public actor InMemoryAuthTokenStore: AuthTokenStore {
    private var tokens: AuthTokenSet?

    public init(tokens: AuthTokenSet? = nil) { self.tokens = tokens }
    public func read() async -> AuthTokenSet? { tokens }
    public func save(_ tokens: AuthTokenSet) async { self.tokens = tokens }
    public func clear() async { tokens = nil }
}

#if canImport(Security)

/// Keychain-backed token storage. The refresh token never enters UserDefaults,
/// logs, or the document cache. Access is device-only and available after the
/// first unlock so background upload can resume safely.
public final class KeychainAuthTokenStore: AuthTokenStore, @unchecked Sendable {
    private let service: String
    private let account: String

    public init(service: String = "com.patientapp.auth", account: String = "active") {
        self.service = service
        self.account = account
    }

    public func read() async -> AuthTokenSet? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return try? JSONDecoder().decode(AuthTokenSet.self, from: data)
    }

    public func save(_ tokens: AuthTokenSet) async {
        guard let data = try? JSONEncoder().encode(tokens) else { return }
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

public typealias KeychainAuthTokenStore = InMemoryAuthTokenStore

#endif

/// Credential-aware authentication is intentionally an additive protocol. The
/// existing fixture/session tests continue using AuthSession, while staging
/// builds opt into real credential exchange and bearer-token refresh.
public protocol CredentialAuthSession: AuthSession, BearerTokenProvider {
    func signIn(username: String, password: String) async throws -> AuthState
    func restoreCredentials() async throws -> AuthState
}

/// Local staging session backed by the `/v1/auth` endpoints. It is not an
/// enterprise OAuth implementation; the server issues a signed local JWT for
/// deterministic development and rotates the refresh token on restore.
public actor StagingAuthSession: CredentialAuthSession {
    private let baseURL: URL
    private let session: URLSession
    private let sessionStore: KeychainSessionStore
    private let tokenStore: any AuthTokenStore
    private var refreshInFlight: _Concurrency.Task<AuthTokenSet, Error>?

    public init(
        baseURL: URL,
        sessionStore: KeychainSessionStore,
        tokenStore: any AuthTokenStore = KeychainAuthTokenStore(),
        session: URLSession = .shared
    ) {
        self.baseURL = baseURL
        self.sessionStore = sessionStore
        self.tokenStore = tokenStore
        self.session = session
    }

    public func currentSession() async -> SessionContext? { await sessionStore.currentSession() }
    public func beginSession(identifier: String) async -> SessionContext { await sessionStore.beginSession(identifier: identifier) }
    public func isCurrent(_ session: SessionContext) async -> Bool { await sessionStore.isCurrent(session) }
    public func authState() async -> AuthState { await sessionStore.authState() }

    /// Compatibility entry point used by fixture-only callers. Staging UI
    /// always calls the credential overload below, so no token is fabricated.
    public func signIn(identifier: String) async -> AuthState {
        await sessionStore.signIn(identifier: identifier)
    }

    public func switchAccount(identifier: String) async -> AuthState {
        await tokenStore.clear()
        return await sessionStore.switchAccount(identifier: identifier)
    }

    public func signIn(username: String, password: String) async throws -> AuthState {
        let normalized = username.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty, !password.isEmpty else { throw AuthSessionError.invalidCredentials }
        let tokens = try await requestTokens(path: "v1/auth/sessions", payload: ["username": normalized, "password": password])
        await tokenStore.save(tokens)
        _ = await sessionStore.signIn(identifier: tokens.subject)
        return await sessionStore.authState()
    }

    public func restoreCredentials() async throws -> AuthState {
        guard let tokens = await tokenStore.read() else {
            // A persisted account epoch without its bearer/refresh pair is not
            // an authenticated staging session (for example after Keychain
            // access was denied or a previous logout). Clear that stale epoch
            // instead of rendering a signed-in shell that cannot make requests.
            await sessionStore.logout()
            return await sessionStore.authState()
        }
        if tokens.isExpiringSoon {
            _ = try await refresh()
        }
        if let current = await sessionStore.currentSession(), current.identifier == tokens.subject {
            return await sessionStore.authState()
        } else {
            _ = await sessionStore.signIn(identifier: tokens.subject)
        }
        return await sessionStore.authState()
    }

    public func restore() async -> AuthState {
        do { return try await restoreCredentials() }
        catch {
            await expire()
            return await sessionStore.authState()
        }
    }

    public func bearerToken() async throws -> String? {
        guard let tokens = await tokenStore.read() else { return nil }
        if tokens.isExpiringSoon {
            return try await refresh().accessToken
        }
        return tokens.accessToken
    }

    public func expire() async {
        refreshInFlight?.cancel()
        refreshInFlight = nil
        await tokenStore.clear()
        await sessionStore.expire()
    }

    public func logout() async {
        refreshInFlight?.cancel()
        refreshInFlight = nil
        if let tokens = await tokenStore.read() {
            _ = try? await request(path: "v1/auth/logout", payload: ["refresh_token": tokens.refreshToken], expected: [204, 200])
        }
        await tokenStore.clear()
        await sessionStore.logout()
    }

    private func refresh() async throws -> AuthTokenSet {
        if let refreshInFlight { return try await refreshInFlight.value }
        guard let current = await tokenStore.read(), !current.refreshToken.isEmpty else {
            throw AuthSessionError.invalidCredentials
        }
        let task = _Concurrency.Task { [baseURL, session] in
            try await Self.requestTokens(baseURL: baseURL, session: session, path: "v1/auth/refresh", payload: ["refresh_token": current.refreshToken])
        }
        refreshInFlight = task
        defer { refreshInFlight = nil }
        let result = try await task.value
        // Logout/expiry can race an in-flight URLSession request. Only persist
        // the response if the same refresh token is still active; this avoids
        // resurrecting a session after the user has signed out.
        guard let latest = await tokenStore.read(), latest.refreshToken == current.refreshToken else {
            throw AuthSessionError.unavailable
        }
        await tokenStore.save(result)
        return result
    }

    private func requestTokens(path: String, payload: [String: String]) async throws -> AuthTokenSet {
        try await Self.requestTokens(baseURL: baseURL, session: session, path: path, payload: payload)
    }

    private static func requestTokens(baseURL: URL, session: URLSession, path: String, payload: [String: String]) async throws -> AuthTokenSet {
        let data = try await request(baseURL: baseURL, session: session, path: path, payload: payload, expected: [200])
        do {
            let response = try JSONDecoder().decode(AuthTokenResponse.self, from: data)
            guard !response.accessToken.isEmpty, !response.refreshToken.isEmpty, !response.subject.isEmpty,
                  let expiresAt = Self.parseDate(response.expiresAt) else { throw AuthSessionError.invalidResponse }
            return AuthTokenSet(accessToken: response.accessToken, refreshToken: response.refreshToken, expiresAt: expiresAt, subject: response.subject)
        } catch let error as AuthSessionError { throw error }
        catch { throw AuthSessionError.invalidResponse }
    }

    private func request(path: String, payload: [String: String], expected: [Int]) async throws -> Data {
        try await Self.request(baseURL: baseURL, session: session, path: path, payload: payload, expected: expected)
    }

    private static func request(baseURL: URL, session: URLSession, path: String, payload: [String: String], expected: [Int]) async throws -> Data {
        guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL else { throw AuthSessionError.configuration }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw AuthSessionError.unavailable }
            guard expected.contains(http.statusCode) else {
                if http.statusCode == 401 || http.statusCode == 403 { throw AuthSessionError.invalidCredentials }
                throw AuthSessionError.unavailable
            }
            return data
        } catch let error as AuthSessionError { throw error }
        catch { throw AuthSessionError.unavailable }
    }

    private static func parseDate(_ value: String) -> Date? {
        let decoder = ISO8601DateFormatter()
        decoder.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return decoder.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }

    private struct AuthTokenResponse: Decodable {
        let accessToken: String
        let refreshToken: String
        let expiresAt: String
        let subject: String

        enum CodingKeys: String, CodingKey {
            case accessToken = "access_token"
            case refreshToken = "refresh_token"
            case expiresAt = "expires_at"
            case subject
        }
    }
}

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
