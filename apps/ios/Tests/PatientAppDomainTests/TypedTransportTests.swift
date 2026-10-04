import Foundation
import XCTest
@testable import PatientAppDomain

final class TypedTransportTests: XCTestCase {
    override func tearDown() {
        TransportStubURLProtocol.handler = nil
        super.tearDown()
    }

    func testURLSessionTransportInjectsAuthorizationAndRetriesIdempotentFailures() async throws {
        let recorder = RequestRecorder()
        TransportStubURLProtocol.handler = { request in
            recorder.append(request)
            let status = recorder.count == 1 ? 503 : 200
            return (HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, Data("{}".utf8))
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [TransportStubURLProtocol.self]
        let transport = try URLSessionPatientAPITransport(
            baseURLProvider: StaticBaseURLProvider(baseURL: URL(string: "https://example.invalid")!),
            tokenProvider: StaticBearerTokenProvider(value: "synthetic-token"),
            requestIDProvider: FixedRequestIDProvider(value: "request-123"),
            session: URLSession(configuration: configuration),
            retryPolicy: PatientAPITransportRetryPolicy(maxAttempts: 2, baseDelay: .zero)
        )

        let response = try await transport.send(PatientAPITransportRequest(method: "GET", path: "/v1/visits", idempotent: true))
        XCTAssertEqual(response.statusCode, 200)
        XCTAssertEqual(recorder.count, 2)
        let request = try XCTUnwrap(recorder.first)
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer synthetic-token")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Request-ID"), "request-123")
    }

    func testURLSessionTransportDoesNotRetryNonIdempotentFailures() async throws {
        let recorder = RequestRecorder()
        TransportStubURLProtocol.handler = { request in
            recorder.append(request)
            return (HTTPURLResponse(url: request.url!, statusCode: 500, httpVersion: nil, headerFields: nil)!, Data())
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [TransportStubURLProtocol.self]
        let transport = try URLSessionPatientAPITransport(
            baseURLProvider: StaticBaseURLProvider(baseURL: URL(string: "https://example.invalid")!),
            tokenProvider: StaticBearerTokenProvider(value: "synthetic-token"),
            requestIDProvider: FixedRequestIDProvider(value: "request-123"),
            session: URLSession(configuration: configuration),
            retryPolicy: PatientAPITransportRetryPolicy(maxAttempts: 3, baseDelay: .zero)
        )

        let response = try await transport.send(PatientAPITransportRequest(method: "POST", path: "/v1/shares", idempotent: false))
        XCTAssertEqual(response.statusCode, 500)
        XCTAssertEqual(recorder.count, 1)
    }

    func testTypedClientMapsSharingAndVisitPackContractResponses() async throws {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let visitID = UUID()
        let topicID = UUID()
        let taskID = UUID()
        let sharePayload = ContractShareVersionPayload(id: UUID(), ownerID: "owner", resourceType: .visit, resourceID: visitID, resourceVersion: 4, expiresAt: now.addingTimeInterval(3600), status: .active, revokedAt: nil, createdAt: now)
        let visitPayload = ContractVisitPayload(title: "Follow-up", startsAt: now, topicIDs: [topicID], id: visitID, ownerID: "owner", version: 4, createdAt: now, updatedAt: now)
        let topicPayload = ContractTopicPayload(name: "Labs", id: topicID, ownerID: "owner", version: 2, createdAt: now, updatedAt: now)
        let taskPayload = ContractTaskPayload(title: "Bring questions", visitID: visitID, dueAt: nil, id: taskID, ownerID: "owner", status: .open, version: 1, createdAt: now, updatedAt: now)
        let transport = ScriptedTransport { request in
            switch request.path {
            case "/v1/shares": return try encodedResponse(ContractShareCreateResponse(share: sharePayload, token: "one-time-token"))
            case "/v1/visits": return try encodedResponse([visitPayload])
            case "/v1/topics": return try encodedResponse([topicPayload])
            case "/v1/tasks": return try encodedResponse([taskPayload])
            default: return PatientAPITransportResponse(statusCode: 404)
            }
        }
        let client = URLSessionPatientAPIClient(transport: transport)

        let share = try await client.createShare(ShareCreateRequest(resourceType: .visit, resourceID: visitID, resourceVersion: 4, expiresAt: Date().addingTimeInterval(3600), idempotencyKey: "share-key"))
        XCTAssertEqual(share.share.resourceID, visitID)
        XCTAssertEqual(share.token, "one-time-token")
        let pack = try await client.visitPack(visitID: visitID)
        XCTAssertEqual(pack.visit.id, visitID)
        XCTAssertEqual(pack.topics.map { $0.id }, [topicID])
        XCTAssertEqual(pack.tasks.map { $0.id }, [taskID])
        let requests = await transport.requests()
        XCTAssertTrue(requests.contains { $0.path == "/v1/shares" && $0.headers["Idempotency-Key"] == "share-key" })
    }

    func testAuthenticatedClientRejectsSignedOutAndAllowsSignedInRequests() async throws {
        let session = InMemorySessionStore()
        let transport = ScriptedTransport { _ in PatientAPITransportResponse(statusCode: 200, body: Data("[]".utf8)) }
        let client = AuthenticatedPatientAPIClient(client: URLSessionPatientAPIClient(transport: transport), authSession: session)
        do {
            _ = try await client.listVisits()
            XCTFail("signed-out requests must be rejected")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .unauthorized)
        }
        _ = await session.signIn(identifier: "patient-1")
        _ = try await client.listVisits()
    }

}

private func encodedResponse<T: Encodable>(_ value: T) throws -> PatientAPITransportResponse {
    let encoder = JSONEncoder()
    encoder.dateEncodingStrategy = .iso8601
    return PatientAPITransportResponse(statusCode: 200, body: try encoder.encode(value))
}

private actor ScriptedTransport: PatientAPITransport {
    private var recorded: [PatientAPITransportRequest] = []
    private let responder: @Sendable (PatientAPITransportRequest) throws -> PatientAPITransportResponse

    init(responder: @escaping @Sendable (PatientAPITransportRequest) throws -> PatientAPITransportResponse) {
        self.responder = responder
    }

    func send(_ request: PatientAPITransportRequest) async throws -> PatientAPITransportResponse {
        recorded.append(request)
        return try responder(request)
    }

    func requests() -> [PatientAPITransportRequest] { recorded }
}

private final class RequestRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var requests: [URLRequest] = []

    var count: Int { lock.lock(); defer { lock.unlock() }; return requests.count }
    var first: URLRequest? { lock.lock(); defer { lock.unlock() }; return requests.first }
    func append(_ request: URLRequest) { lock.lock(); defer { lock.unlock() }; requests.append(request) }
}

private final class TransportStubURLProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var handler: ((URLRequest) -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.handler, let client else { return }
        let (response, data) = handler(request)
        client.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client.urlProtocol(self, didLoad: data)
        client.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
