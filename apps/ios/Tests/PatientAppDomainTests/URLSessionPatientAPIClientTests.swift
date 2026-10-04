import Foundation
import XCTest
@testable import PatientAppDomain

final class URLSessionPatientAPIClientTests: XCTestCase {
    private let documentID = UUID()
    private let factID = UUID()

    override func tearDown() {
        StubURLProtocol.handler = nil
        super.tearDown()
    }

    func testCreateImportEncodesContractFieldsAndInjectedHeaders() async throws {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let payload = ContractDocumentPayload(filename: "synthetic.pdf", mediaType: "application/pdf", sizeBytes: 42, sha256: String(repeating: "a", count: 64), id: documentID, ownerID: "owner", sourceType: .uploadedDocument, status: .uploaded, version: 1, createdAt: now, updatedAt: now, deletedAt: nil)
        let responseData = try JSONEncoder.iso8601.encode(payload)
        let client = try makeClient { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/v1/documents")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-token")
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-Request-ID"), "request-123")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Idempotency-Key"), "request-123")
            let body = try request.bodyData().jsonObject()
            XCTAssertEqual(body["filename"] as? String, "synthetic.pdf")
            XCTAssertEqual(body["media_type"] as? String, "application/pdf")
            XCTAssertEqual(body["size_bytes"] as? Int, 42)
            return (200, responseData)
        }

        let ticket = try await client.createImport(ImportRequest(fileName: "synthetic.pdf", title: "Synthetic", byteCount: 42, mediaType: "application/pdf", sha256: String(repeating: "a", count: 64)))
        XCTAssertEqual(ticket.documentID, documentID)
        XCTAssertEqual(ticket.title, "synthetic.pdf")
    }

    func testConfirmFactEncodesReviewBodyAndIfMatchHeader() async throws {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let payload = ContractFactPayload(label: "Label", value: "Value", sourceRef: "page:1", sourceType: .ocr, confidence: 0.9, documentID: documentID, topicID: nil, id: factID, ownerID: "owner", reviewStatus: .confirmed, version: 3, createdAt: now, updatedAt: now)
        let responseData = try JSONEncoder.iso8601.encode(payload)
        let client = try makeClient { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/v1/facts/\(self.factID.uuidString)/review")
            XCTAssertEqual(request.value(forHTTPHeaderField: "If-Match-Version"), "3")
            let body = try request.bodyData().jsonObject()
            XCTAssertEqual(body["review_status"] as? String, "confirmed")
            XCTAssertNil(body["if_match_version"])
            return (200, responseData)
        }

        let fact = try await client.confirmFact(FactReviewCommand(documentID: documentID, factID: factID, ifMatchVersion: 3))
        XCTAssertEqual(fact.reviewStatus, .confirmed)
        XCTAssertTrue(fact.canAppearInDoctorView)
    }

    func testProcessingStatusDecodesDocumentStatus() async throws {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let payload = ContractDocumentPayload(filename: "synthetic.pdf", mediaType: "application/pdf", sizeBytes: 42, sha256: String(repeating: "b", count: 64), id: documentID, ownerID: "owner", sourceType: .uploadedDocument, status: .processing, version: 2, createdAt: now, updatedAt: now, deletedAt: nil)
        let responseData = try JSONEncoder.iso8601.encode(payload)
        let client = try makeClient { _ in (200, responseData) }
        let status = try await client.processingStatus(documentID: documentID)
        XCTAssertEqual(status, .processing)
    }

    func testHTTPErrorsMapToTypedClientErrors() async throws {
        let client = try makeClient { _ in (409, Data()) }
        do {
            _ = try await client.confirmFact(FactReviewCommand(documentID: documentID, factID: factID, ifMatchVersion: 1))
            XCTFail("Expected a version conflict")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .versionConflict)
        }
    }

    func testMissingTokenAndUnsupportedEditAreExplicit() async throws {
        let noTokenClient = try makeClient(token: nil) { _ in XCTFail("No request should be sent"); return (200, Data()) }
        do {
            _ = try await noTokenClient.processingStatus(documentID: documentID)
            XCTFail("Expected missing token")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .missingBearerToken)
        }

        let client = try makeClient { _ in XCTFail("Edit is not supported by this contract"); return (200, Data()) }
        do {
            _ = try await client.editFact(FactEditCommand(documentID: documentID, factID: factID, value: "Edited"))
            XCTFail("Expected unsupported operation")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .unsupported(.factEditNotInContract))
        }
    }

    func testCreateTopicUsesSnakeCaseContractAndIdempotencyHeader() async throws {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let payload = ContractTopicPayload(name: "Symptoms", id: UUID(), ownerID: "owner", version: 1, createdAt: now, updatedAt: now)
        let responseData = try JSONEncoder.iso8601.encode(payload)
        let client = try makeClient { request in
            XCTAssertEqual(request.url?.path, "/v1/topics")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Idempotency-Key"), "request-123")
            let body = try request.bodyData().jsonObject()
            XCTAssertEqual(body["name"] as? String, "Symptoms")
            return (201, responseData)
        }

        let topic = try await client.createTopic(TopicCreateRequest(name: "Symptoms"))
        XCTAssertEqual(topic.name, "Symptoms")
    }

    func testCreateVisitAndTaskEncodeNullableDatesAndDecodeResponses() async throws {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let visitID = UUID()
        let taskID = UUID()
        var requests: [URLRequest] = []
        let visitPayload = ContractVisitPayload(title: "Follow-up", startsAt: nil, topicIDs: [], id: visitID, ownerID: "owner", version: 1, createdAt: now, updatedAt: now)
        let taskPayload = ContractTaskPayload(title: "Bring questions", visitID: nil, dueAt: nil, id: taskID, ownerID: "owner", status: .open, version: 1, createdAt: now, updatedAt: now)
        var responseData = try JSONEncoder.iso8601.encode(visitPayload)
        let client = try makeClient { request in
            requests.append(request)
            if request.url?.path == "/v1/tasks" {
                responseData = try JSONEncoder.iso8601.encode(taskPayload)
            }
            return (201, responseData)
        }

        let visit = try await client.createVisit(VisitCreateRequest(title: "Follow-up"))
        let task = try await client.createTask(TaskCreateRequest(title: "Bring questions"))
        XCTAssertEqual(visit.id, visitID)
        XCTAssertNil(visit.scheduledAt)
        XCTAssertEqual(task.id, taskID)
        XCTAssertNil(task.visitID)
        XCTAssertEqual(requests.count, 2)
        let visitBody = try requests[0].bodyData().jsonObject()
        XCTAssertTrue(visitBody["starts_at"] is NSNull)
        XCTAssertTrue(visitBody["topic_ids"] is [Any])
        let taskBody = try requests[1].bodyData().jsonObject()
        XCTAssertTrue(taskBody["visit_id"] is NSNull)
        XCTAssertTrue(taskBody["due_at"] is NSNull)
    }

    private func makeClient(token: String? = "test-token", handler: @escaping (URLRequest) throws -> (Int, Data)) throws -> URLSessionPatientAPIClient {
        StubURLProtocol.handler = { request in
            do {
                let (status, data) = try handler(request)
                let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
                return (response, data)
            } catch {
                return (HTTPURLResponse(url: request.url!, statusCode: 500, httpVersion: nil, headerFields: nil)!, Data())
            }
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        return try URLSessionPatientAPIClient(baseURLProvider: StaticBaseURLProvider(baseURL: URL(string: "https://example.invalid")!), tokenProvider: StaticBearerTokenProvider(value: token), requestIDProvider: FixedRequestIDProvider(value: "request-123"), session: URLSession(configuration: configuration))
    }
}

private final class StubURLProtocol: URLProtocol, @unchecked Sendable {
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

private extension JSONEncoder {
    static var iso8601: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }
}

private extension Data {
    func jsonObject() throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: self) as? [String: Any])
    }
}

private extension URLRequest {
    func bodyData() throws -> Data {
        if let httpBody { return httpBody }
        guard let stream = httpBodyStream else { throw PatientAPIClientError.invalidRequest }
        stream.open()
        defer { stream.close() }
        var result = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count < 0 { throw PatientAPIClientError.invalidRequest }
            if count == 0 { break }
            result.append(buffer, count: count)
        }
        return result
    }
}
