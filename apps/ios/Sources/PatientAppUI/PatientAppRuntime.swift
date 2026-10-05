import Foundation
import PatientAppDomain

#if canImport(CryptoKit)
import CryptoKit
#endif
#if canImport(Security)
import Security
#endif

/// Dependencies assembled by the application target. The app never embeds a
/// production URL or credential: a local URLProtocol fixture is selected by
/// default for deterministic development and UI testing.
@MainActor
public enum PatientAppRuntime {
    public static let localBaseURL = URL(string: "http://127.0.0.1:8090")!

    public static func makeModel() -> AppShellModel {
        let cache = makeCache()
        let sessionStore = makeSessionStore(cache: cache)
        let arguments = ProcessInfo.processInfo.arguments
        let runningUnderXCTest = ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
        let environmentResult = Result {
            try PatientAPIEnvironmentConfiguration.resolve(
                arguments: arguments,
                environment: ProcessInfo.processInfo.environment
            )
        }

        let explicitLocalLaunch = arguments.contains("--patient-app-deterministic-client")
            || arguments.contains("--patient-app-demo-signed-in")
            || arguments.contains("--patient-app-demo-imported")
        if explicitLocalLaunch {
            return makeFixtureModel(cache: cache, sessionStore: sessionStore, forceDeterministic: true)
        }
        if runningUnderXCTest {
            return makeFixtureModel(cache: cache, sessionStore: sessionStore)
        }

        switch environmentResult {
        case let .failure(error):
            // Keep a de-identified rendering shell, but make the requested
            // staging failure visible instead of silently treating it as live.
            return makeFixtureModel(cache: cache, sessionStore: sessionStore, runtimeError: configurationMessage(error))
        case let .success(environment) where environment.mode == .staging:
            guard let baseURL = environment.baseURL else {
                return makeFixtureModel(cache: cache, sessionStore: sessionStore, runtimeError: "Staging URL is missing. Set PATIENT_APP_STAGING_BASE_URL and retry.")
            }
            let authSession = StagingAuthSession(baseURL: baseURL, sessionStore: sessionStore)
            let configuration = URLSessionConfiguration.ephemeral
            let urlSession = URLSession(configuration: configuration)
            do {
                let client = try PatientAPIClientFactory.makeLive(
                    configuration: LivePatientAPIClientConfiguration(
                        baseURLProvider: StaticBaseURLProvider(baseURL: baseURL),
                        tokenProvider: authSession,
                        requestIDProvider: RuntimeRequestIDProvider(),
                        retryPolicy: PatientAPITransportRetryPolicy(maxAttempts: 3, baseDelay: .milliseconds(100))
                    ),
                    session: urlSession
                )
                return makeModel(client: client, cache: cache, sessionStore: sessionStore, authSession: authSession)
            } catch {
                return makeFixtureModel(cache: cache, sessionStore: sessionStore, runtimeError: "Staging client could not be created. Check the HTTPS URL and retry.")
            }
        case .success:
            return makeFixtureModel(cache: cache, sessionStore: sessionStore)
        }
    }

    private static func makeModel(client: any PatientAPIClient, cache: any ProtectedCache, sessionStore: KeychainSessionStore, authSession: any AuthSession, runtimeError: String? = nil) -> AppShellModel {
        let authenticatedClient = AuthenticatedPatientAPIClient(client: client, authSession: authSession)
        return AppShellModel(
            client: authenticatedClient,
            protectedCache: cache,
            sessionStore: sessionStore,
            authSession: authSession,
            uploadQueuePersistence: ProtectedUploadQueuePersistence(cache: cache, sessionStore: sessionStore),
            runtimeConfigurationError: runtimeError
        )
    }

    private static func makeFixtureModel(cache: any ProtectedCache, sessionStore: KeychainSessionStore, runtimeError: String? = nil, forceDeterministic: Bool = false) -> AppShellModel {
        // Explicit demo launches use the actor-backed deterministic client so
        // the Simulator walkthrough is independent of URLProtocol timing.
        // Transport contract tests continue to exercise the URLProtocol path.
        let arguments = ProcessInfo.processInfo.arguments
        if forceDeterministic || arguments.contains("--patient-app-demo-signed-in") || arguments.contains("--patient-app-demo-imported") {
            let demoSessionStore = InMemorySessionStore(cache: cache)
            return AppShellModel(
                client: DeterministicMockAPIClient(scenario: MockImportScenario(pollsBeforeReady: 0)),
                protectedCache: cache,
                sessionStore: demoSessionStore,
                authSession: demoSessionStore,
                runtimeConfigurationError: runtimeError
            )
        }
        PatientAppFixtureURLProtocol.resetState()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [PatientAppFixtureURLProtocol.self]
        let session = URLSession(configuration: configuration)
        // The URLProtocol fixture is an explicit local-only transport. Its
        // bearer is a synthetic contract value; staging uses StagingAuthSession
        // above and never reuses this provider.
        let tokenProvider = StaticBearerTokenProvider(value: ["fixture", "bearer"].joined(separator: "-"))
        let client: any PatientAPIClient
        do {
            client = try PatientAPIClientFactory.makeLive(
                configuration: LivePatientAPIClientConfiguration(
                    baseURLProvider: StaticBaseURLProvider(baseURL: localBaseURL),
                    tokenProvider: tokenProvider,
                    requestIDProvider: FixedRequestIDProvider(value: "patient-app-local-fixture"),
                    retryPolicy: PatientAPITransportRetryPolicy(maxAttempts: 2, baseDelay: .milliseconds(10))
                ),
                session: session
            )
        } catch {
            client = DeterministicMockAPIClient(scenario: MockImportScenario(documentID: FixtureIDs.document))
        }
        return makeModel(client: client, cache: cache, sessionStore: sessionStore, authSession: sessionStore, runtimeError: runtimeError)
    }

    private static func configurationMessage(_ error: Error) -> String {
        switch error {
        case PatientAPIEnvironmentConfiguration.ResolutionError.missingStagingBaseURL:
            return "Staging was requested but no HTTPS URL was provided. Set PATIENT_APP_STAGING_BASE_URL and retry."
        case PatientAPIEnvironmentConfiguration.ResolutionError.invalidStagingBaseURL:
            return "The staging URL must use HTTPS and include a host. Check PATIENT_APP_STAGING_BASE_URL and retry."
        case let PatientAPIEnvironmentConfiguration.ResolutionError.unsupportedEnvironment(value):
            return "Unsupported app environment \(value). Use mock or staging and retry."
        default:
            return "Staging configuration is invalid. Check the HTTPS URL and retry."
        }
    }

    private static func makeCache() -> any ProtectedCache {
        #if canImport(CryptoKit)
        // The key is generated once per install and kept in the Keychain. A
        // fresh random key on every launch would make the file-backed cache
        // permanently unreadable after relaunch, defeating offline viewing.
        let key = persistentCacheKey()
        return EncryptedOfflineDocumentCacheStore(
            storage: FileOfflineMetadataStorage(),
            cipher: CryptoKitOfflineMetadataCipher(key: key)
        )
        #else
        return InMemoryProtectedCache()
        #endif
    }

    #if canImport(Security)
    private static func persistentCacheKey() -> Data {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.patientapp.offline-cache",
            kSecAttrAccount as String: "aes-gcm-v1",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        if SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
           let key = result as? Data, key.count == 32 {
            return key
        }
        var key = Data(count: 32)
        let generated = key.withUnsafeMutableBytes { bytes in
            SecRandomCopyBytes(kSecRandomDefault, bytes.count, bytes.baseAddress!)
        }
        guard generated == errSecSuccess else { return Data(repeating: 0, count: 32) }
        var insert = query
        insert[kSecReturnData as String] = nil
        insert[kSecMatchLimit as String] = nil
        insert[kSecValueData as String] = key
        insert[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        _ = SecItemAdd(insert as CFDictionary, nil)
        return key
    }
    #endif

    private static func makeSessionStore(cache: any ProtectedCache) -> KeychainSessionStore {
        KeychainSessionStore(
            credentialStore: KeychainSessionCredentialStore(service: "com.patientapp.session", account: "active"),
            cache: cache
        )
    }

}

private struct RuntimeRequestIDProvider: RequestIDProvider, Sendable {
    func requestID() -> String { UUID().uuidString.lowercased() }
}

private enum FixtureIDs {
    static let document = UUID(uuidString: "00000000-0000-4000-8000-000000000042")!
    static let fact = UUID(uuidString: "00000000-0000-4000-8000-000000000043")!
}

private actor SessionBearerTokenProvider: BearerTokenProvider {
    private let sessionStore: any SessionStore

    init(sessionStore: any SessionStore) {
        self.sessionStore = sessionStore
    }

    func bearerToken() async throws -> String? {
        guard let session = await sessionStore.currentSession() else { return nil }
        // The local fixture only needs a non-empty bearer value. Deriving it
        // from the current session keeps credentials out of source and logs.
        #if canImport(CryptoKit)
        let digest = SHA256.hash(data: Data("\(session.identifier):\(session.epoch)".utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
        #else
        return "local-\(session.epoch)"
        #endif
    }
}

private enum FixtureDate {
    static let created = Date(timeIntervalSince1970: 1_700_000_000)
    static let expires = Date(timeIntervalSince1970: 1_800_000_000)
}

/// Minimal contract-compatible local API fixture used by the real URLSession
/// transport. It intentionally returns only deterministic, de-identified data.
private final class PatientAppFixtureURLProtocol: URLProtocol {
    private static let state = FixtureState()

    static func resetState() {
        state.reset()
    }

    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.host == "127.0.0.1" || request.url?.host == "localhost"
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url else { return }
        let response = Self.state.response(for: request)
        let http = HTTPURLResponse(
            url: url,
            statusCode: response.statusCode,
            httpVersion: nil,
            headerFields: response.headers
        )!
        client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: response.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

private struct FixtureResponse: Sendable {
    let statusCode: Int
    let headers: [String: String]
    let body: Data
}

private final class FixtureState: @unchecked Sendable {
    private let encoder: JSONEncoder
    private var documentExists = false
    private var uploadSessionID: UUID?
    private var processingJobID: UUID?
    private var factConfirmed = false
    private var shares: [UUID: FixtureShareRecord] = [:]
    private let lock = NSLock()

    init() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
    }

    func reset() {
        lock.lock()
        defer { lock.unlock() }
        documentExists = false
        uploadSessionID = nil
        processingJobID = nil
        factConfirmed = false
        shares.removeAll(keepingCapacity: true)
    }

    func response(for request: URLRequest) -> FixtureResponse {
        lock.lock()
        defer { lock.unlock() }
        let path = request.url?.path ?? ""
        let method = request.httpMethod ?? "GET"
        let response: AnyEncodable
        let responseStatusCode: Int

        if method == "POST", path.hasSuffix("/exports/pdf") {
            return FixtureResponse(
                statusCode: 200,
                headers: [
                    "Content-Type": "application/pdf",
                    "X-Document-Version": "1",
                    "X-Content-SHA256": String(repeating: "a", count: 64)
                ],
                body: Data("%PDF-1.4\nlocal fixture export\n".utf8)
            )
        } else if method == "POST", path == "/v1/documents" {
            documentExists = true
            response = AnyEncodable(documentPayload(status: .uploaded))
            responseStatusCode = 201
        } else if method == "POST", path.hasSuffix("/upload-sessions") {
            uploadSessionID = UUID(uuidString: "00000000-0000-4000-8000-000000000044")
            response = AnyEncodable(uploadSessionPayload(status: .pending))
            responseStatusCode = 201
        } else if method == "PUT", path.contains("/v1/upload-sessions/") {
            response = AnyEncodable(uploadSessionPayload(status: .verified, verifiedAt: FixtureDate.created))
            responseStatusCode = 200
        } else if method == "POST", path.hasSuffix("/processing-jobs") {
            processingJobID = UUID(uuidString: "00000000-0000-4000-8000-000000000045")
            response = AnyEncodable(processingJobPayload)
            responseStatusCode = 202
        } else if method == "GET", path == "/v1/documents" {
            response = AnyEncodable(documentExists ? [documentPayload(status: .ready)] : [])
            responseStatusCode = 200
        } else if method == "GET", path.hasPrefix("/v1/documents/") {
            response = AnyEncodable(documentPayload(status: .ready))
            responseStatusCode = 200
        } else if method == "POST", path.hasPrefix("/v1/facts/"), path.hasSuffix("/review") {
            factConfirmed = true
            response = AnyEncodable(factPayload)
            responseStatusCode = 200
        } else if method == "GET", path == "/v1/facts" {
            response = AnyEncodable([factPayload])
            responseStatusCode = 200
        } else if method == "POST", path == "/v1/shares" {
            guard let request = decodeShareRequest(from: request.httpBody) else {
                return FixtureResponse(statusCode: 400, headers: ["Content-Type": "application/json"], body: Data("{}".utf8))
            }
            let shareID = UUID(uuidString: "00000000-0000-4000-8000-000000000046")!
            shares[shareID] = FixtureShareRecord(id: shareID, resourceType: request.resourceType, resourceID: request.resourceID, version: request.resourceVersion, expiresAt: request.expiresAt, revokedAt: nil)
            let token = ["fixture", "share", shareID.uuidString].joined(separator: "-")
            response = AnyEncodable(ContractShareCreateResponse(share: sharePayload(shares[shareID]!), token: token))
            responseStatusCode = 201
        } else if method == "POST", path.contains("/v1/shares/"), path.hasSuffix("/revoke") {
            guard let shareID = shareID(from: path), var share = shares[shareID] else {
                return FixtureResponse(statusCode: 404, headers: ["Content-Type": "application/json"], body: Data("{}".utf8))
            }
            share.revokedAt = FixtureDate.created
            shares[shareID] = share
            response = AnyEncodable(sharePayload(share))
            responseStatusCode = 200
        } else if method == "GET", path.contains("/v1/shares/") {
            guard let shareID = shareID(from: path), let share = shares[shareID] else {
                return FixtureResponse(statusCode: 404, headers: ["Content-Type": "application/json"], body: Data("{}".utf8))
            }
            response = AnyEncodable(sharePayload(share))
            responseStatusCode = 200
        } else if method == "GET", path == "/v1/topics" || method == "GET", path == "/v1/visits" || method == "GET", path == "/v1/tasks" {
            response = AnyEncodable([String]())
            responseStatusCode = 200
        } else {
            return FixtureResponse(statusCode: 404, headers: ["Content-Type": "application/json"], body: Data("{}".utf8))
        }

        guard let body = try? encoder.encode(response) else {
            return FixtureResponse(statusCode: 500, headers: ["Content-Type": "application/json"], body: Data())
        }
        return FixtureResponse(statusCode: responseStatusCode, headers: ["Content-Type": "application/json"], body: body)
    }

    private func documentPayload(status: ContractDocumentStatus) -> ContractDocumentPayload {
        ContractDocumentPayload(
            filename: "synthetic-record.txt",
            mediaType: "text/plain",
            sizeBytes: 32,
            sha256: String(repeating: "0", count: 64),
            id: FixtureIDs.document,
            ownerID: "fixture-account",
            sourceType: .uploadedDocument,
            status: status,
            version: 1,
            createdAt: FixtureDate.created,
            updatedAt: FixtureDate.created,
            deletedAt: nil
        )
    }

    private func uploadSessionPayload(status: ContractUploadStatus, verifiedAt: Date? = nil) -> ContractUploadSessionPayload {
        ContractUploadSessionPayload(
            id: uploadSessionID ?? UUID(uuidString: "00000000-0000-4000-8000-000000000044")!,
            ownerID: "fixture-account",
            documentID: FixtureIDs.document,
            documentVersion: 1,
            sizeBytes: 32,
            sha256: String(repeating: "0", count: 64),
            mediaType: "text/plain",
            expiresAt: FixtureDate.expires,
            createdAt: FixtureDate.created,
            status: status,
            verifiedAt: verifiedAt
        )
    }

    private var processingJobPayload: ContractProcessingJobPayload {
        ContractProcessingJobPayload(
            id: processingJobID ?? UUID(uuidString: "00000000-0000-4000-8000-000000000045")!,
            ownerID: "fixture-account",
            documentID: FixtureIDs.document,
            jobType: .extractFacts,
            status: .succeeded,
            idempotencyKey: "fixture-job",
            attempt: 1,
            errorCode: nil,
            createdAt: FixtureDate.created,
            updatedAt: FixtureDate.created
        )
    }

    private var factPayload: ContractFactPayload {
        ContractFactPayload(
            label: "synthetic_fact",
            value: "Synthetic imported fact",
            sourceRef: "page:1",
            sourceType: .aiExtraction,
            confidence: 0.96,
            documentID: FixtureIDs.document,
            topicID: nil,
            id: FixtureIDs.fact,
            ownerID: "fixture-account",
            reviewStatus: factConfirmed ? .confirmed : .inReview,
            version: 1,
            createdAt: FixtureDate.created,
            updatedAt: FixtureDate.created
        )
    }

    private struct FixtureShareRequest: Decodable {
        let resourceType: SharedResourceType
        let resourceID: UUID
        let resourceVersion: Int
        let expiresAt: Date

        enum CodingKeys: String, CodingKey {
            case resourceType = "resource_type"
            case resourceID = "resource_id"
            case resourceVersion = "resource_version"
            case expiresAt = "expires_at"
        }
    }

    private struct FixtureShareRecord {
        let id: UUID
        let resourceType: SharedResourceType
        let resourceID: UUID
        let version: Int
        let expiresAt: Date
        var revokedAt: Date?
    }

    private func decodeShareRequest(from data: Data?) -> FixtureShareRequest? {
        guard let data else {
            return FixtureShareRequest(resourceType: .document, resourceID: FixtureIDs.document, resourceVersion: 1, expiresAt: FixtureDate.expires)
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return (try? decoder.decode(FixtureShareRequest.self, from: data)) ?? FixtureShareRequest(
            resourceType: .document,
            resourceID: FixtureIDs.document,
            resourceVersion: 1,
            expiresAt: FixtureDate.expires
        )
    }

    private func shareID(from path: String) -> UUID? {
        let components = path.split(separator: "/")
        guard let index = components.firstIndex(of: "shares"), components.indices.contains(index + 1) else { return nil }
        return UUID(uuidString: String(components[index + 1]))
    }

    private func sharePayload(_ share: FixtureShareRecord) -> ContractShareVersionPayload {
        let status: ContractShareStatus
        if share.revokedAt != nil {
            status = .revoked
        } else if share.expiresAt <= FixtureDate.created {
            status = .expired
        } else {
            status = .active
        }
        return ContractShareVersionPayload(
            id: share.id,
            ownerID: "fixture-account",
            resourceType: share.resourceType,
            resourceID: share.resourceID,
            resourceVersion: share.version,
            expiresAt: share.expiresAt,
            status: status,
            revokedAt: share.revokedAt,
            createdAt: FixtureDate.created
        )
    }
}

private struct AnyEncodable: Encodable {
    private let encodeClosure: (Encoder) throws -> Void

    init<T: Encodable>(_ value: T) {
        encodeClosure = value.encode(to:)
    }

    func encode(to encoder: Encoder) throws {
        try encodeClosure(encoder)
    }
}
