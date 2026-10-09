import XCTest
@testable import PatientAppDomain

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

final class AuthSessionTests: XCTestCase {
    func testSignInRestoreSwitchAndLogoutStates() async {
        let cache = InMemoryProtectedCache()
        let session = InMemorySessionStore(cache: cache)

        let initial = await session.authState()
        let signedIn = await session.signIn(identifier: "account-a")
        let restored = await session.restore()
        let switched = await session.switchAccount(identifier: "account-b")
        await session.logout()
        let finalState = await session.authState()

        XCTAssertEqual(initial, .signedOut)
        guard case let .signedIn(first) = signedIn,
              case let .signedIn(restoredContext) = restored,
              case let .signedIn(second) = switched else {
            return XCTFail("Expected signed-in states")
        }
        XCTAssertEqual(first, restoredContext)
        XCTAssertNotEqual(first, second)
        XCTAssertEqual(finalState, .signedOut)
    }

    func testExpirePurgesCacheAndRequiresFreshEpoch() async {
        let cache = InMemoryProtectedCache()
        let session = InMemorySessionStore(cache: cache)
        guard case let .signedIn(context) = await session.signIn(identifier: "account-a") else {
            return XCTFail("Expected signed-in state")
        }
        await cache.setData(Data("old".utf8), forKey: "history", session: context)

        await session.expire()
        let state = await session.authState()
        let current = await session.currentSession()
        let oldData = await cache.data(forKey: "history", session: context)
        let oldIsCurrent = await session.isCurrent(context)
        let restored = await session.restore()
        let signedInAgain = await session.signIn(identifier: "account-a")

        XCTAssertEqual(state, .expired)
        XCTAssertNil(current)
        XCTAssertNil(oldData)
        XCTAssertFalse(oldIsCurrent)
        XCTAssertEqual(restored, .expired)
        guard case let .signedIn(newContext) = signedInAgain else {
            return XCTFail("Expected a fresh signed-in state")
        }
        XCTAssertEqual(newContext.identifier, context.identifier)
        XCTAssertGreaterThan(newContext.epoch, context.epoch)
    }

    func testConcurrentAccountSwitchesProduceDistinctEpochs() async {
        let session = InMemorySessionStore()
        async let first = session.switchAccount(identifier: "account-a")
        async let second = session.switchAccount(identifier: "account-b")
        let results = await [first, second]
        let contexts = results.compactMap { state -> SessionContext? in
            guard case let .signedIn(context) = state else { return nil }
            return context
        }
        let current = await session.currentSession()

        XCTAssertEqual(contexts.count, 2)
        XCTAssertEqual(Set(contexts.map(\.epoch)).count, 2)
        XCTAssertEqual(current?.epoch, 2)
        XCTAssertTrue(current.map { contexts.contains($0) } ?? false)
    }

    func testStagingCredentialsIssueBearerRefreshAndLogoutWithoutFabrication() async throws {
        StagingAuthFixtureURLProtocol.reset()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StagingAuthFixtureURLProtocol.self]
        let urlSession = URLSession(configuration: configuration)
        let credentialStore = InMemorySessionCredentialStore()
        let sessionStore = KeychainSessionStore(credentialStore: credentialStore, cache: InMemoryProtectedCache())
        let tokenStore = InMemoryAuthTokenStore()
        let auth = StagingAuthSession(
            baseURL: URL(string: "https://staging-auth.test")!,
            sessionStore: sessionStore,
            tokenStore: tokenStore,
            session: urlSession
        )

        let fixtureUsername = ["synthetic", "user"].joined(separator: "-")
        let fixturePassword = ["synthetic", "password"].joined(separator: "-")
        guard case let .signedIn(context) = try await auth.signIn(username: fixtureUsername, password: fixturePassword) else {
            return XCTFail("expected signed-in state")
        }
        XCTAssertEqual(context.identifier, "synthetic-user")
        let initialToken = try await auth.bearerToken()
        XCTAssertEqual(initialToken, "access-initial")

        // Simulate an app relaunch after the access token expired. Restore
        // must refresh and persist the rotated access/refresh pair.
        await tokenStore.save(AuthTokenSet(accessToken: "access-initial", refreshToken: "refresh-initial", expiresAt: Date().addingTimeInterval(-1), subject: "synthetic-user"))
        guard case let .signedIn(restored) = try await auth.restoreCredentials() else {
            return XCTFail("expected restored signed-in state")
        }
        XCTAssertEqual(restored.identifier, "synthetic-user")
        let refreshedToken = try await auth.bearerToken()
        XCTAssertEqual(refreshedToken, "access-refreshed")
        let refreshedCredentials = await tokenStore.read()
        XCTAssertEqual(refreshedCredentials?.refreshToken, "refresh-refreshed")

        await auth.logout()
        let clearedCredentials = await tokenStore.read()
        XCTAssertNil(clearedCredentials)
        XCTAssertEqual(StagingAuthFixtureURLProtocol.paths, ["/v1/auth/sessions", "/v1/auth/refresh", "/v1/auth/logout"])
    }

    func testStagingCredentialFailureDoesNotCreateSession() async {
        StagingAuthFixtureURLProtocol.reset()
        StagingAuthFixtureURLProtocol.rejectCredentials = true
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StagingAuthFixtureURLProtocol.self]
        let sessionStore = KeychainSessionStore(credentialStore: InMemorySessionCredentialStore(), cache: InMemoryProtectedCache())
        let auth = StagingAuthSession(
            baseURL: URL(string: "https://staging-auth.test")!,
            sessionStore: sessionStore,
            tokenStore: InMemoryAuthTokenStore(),
            session: URLSession(configuration: configuration)
        )

        do {
            _ = try await auth.signIn(username: "wrong", password: "wrong")
            XCTFail("expected invalid credentials")
        } catch {
            XCTAssertEqual(error as? AuthSessionError, .invalidCredentials)
        }
        let currentSession = await auth.currentSession()
        XCTAssertNil(currentSession)
        let missingToken = try? await auth.bearerToken()
        XCTAssertNil(missingToken ?? nil)
    }

    func testStagingRestoreClearsStaleAccountWithoutBearer() async {
        let sessionStore = KeychainSessionStore(credentialStore: InMemorySessionCredentialStore(), cache: InMemoryProtectedCache())
        _ = await sessionStore.signIn(identifier: "stale-account")
        let auth = StagingAuthSession(
            baseURL: URL(string: "https://staging-auth.test")!,
            sessionStore: sessionStore,
            tokenStore: InMemoryAuthTokenStore(),
            session: URLSession(configuration: .ephemeral)
        )

        let restored = try? await auth.restoreCredentials()
        XCTAssertEqual(restored, .signedOut)
        let currentSession = await auth.currentSession()
        let state = await auth.authState()
        XCTAssertNil(currentSession)
        XCTAssertEqual(state, .signedOut)
    }
}

private final class StagingAuthFixtureURLProtocol: URLProtocol {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var recordedPaths: [String] = []
    nonisolated(unsafe) fileprivate static var rejectCredentials = false

    fileprivate static var paths: [String] {
        lock.lock(); defer { lock.unlock() }
        return recordedPaths
    }

    fileprivate static func reset() {
        lock.lock()
        recordedPaths.removeAll(keepingCapacity: true)
        rejectCredentials = false
        lock.unlock()
    }

    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.host == "staging-auth.test"
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let path = request.url?.path ?? ""
        Self.lock.lock()
        Self.recordedPaths.append(path)
        let rejected = Self.rejectCredentials && path == "/v1/auth/sessions"
        Self.lock.unlock()

        let status = rejected ? 401 : (path == "/v1/auth/logout" ? 204 : 200)
        let body: Data
        if rejected {
            body = Data("{\"error\":\"invalid_credentials\"}".utf8)
        } else if path == "/v1/auth/sessions" {
            body = Self.tokenResponse(access: "access-initial", refresh: "refresh-initial", expiresAt: Date().addingTimeInterval(3600))
        } else if path == "/v1/auth/refresh" {
            body = Self.tokenResponse(access: "access-refreshed", refresh: "refresh-refreshed", expiresAt: Date().addingTimeInterval(3600))
        } else {
            body = Data()
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if !body.isEmpty { client?.urlProtocol(self, didLoad: body) }
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private static func tokenResponse(access: String, refresh: String, expiresAt: Date) -> Data {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let object: [String: String] = [
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": formatter.string(from: expiresAt),
            "subject": "synthetic-user",
            "token_type": "Bearer"
        ]
        return try! JSONSerialization.data(withJSONObject: object)
    }
}
