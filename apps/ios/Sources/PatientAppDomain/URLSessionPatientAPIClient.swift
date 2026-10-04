import Foundation

public protocol APIBaseURLProvider: Sendable {
    var baseURL: URL { get }
}

public protocol BearerTokenProvider: Sendable {
    func bearerToken() async throws -> String?
}

public protocol RequestIDProvider: Sendable {
    func requestID() -> String
}

public struct StaticBaseURLProvider: APIBaseURLProvider, Sendable {
    public let baseURL: URL

    public init(baseURL: URL) {
        self.baseURL = baseURL
    }
}

public struct StaticBearerTokenProvider: BearerTokenProvider, Sendable {
    private let value: String?

    public init(value: String?) {
        self.value = value
    }

    public func bearerToken() async throws -> String? { value }
}

public struct FixedRequestIDProvider: RequestIDProvider, Sendable {
    private let value: String

    public init(value: String) {
        self.value = value
    }

    public func requestID() -> String { value }
}

public struct LivePatientAPIClientConfiguration: Sendable {
    public let baseURLProvider: any APIBaseURLProvider
    public let tokenProvider: any BearerTokenProvider
    public let requestIDProvider: any RequestIDProvider
    public let retryPolicy: PatientAPITransportRetryPolicy

    public init(baseURLProvider: any APIBaseURLProvider, tokenProvider: any BearerTokenProvider, requestIDProvider: any RequestIDProvider, retryPolicy: PatientAPITransportRetryPolicy = PatientAPITransportRetryPolicy()) {
        self.baseURLProvider = baseURLProvider
        self.tokenProvider = tokenProvider
        self.requestIDProvider = requestIDProvider
        self.retryPolicy = retryPolicy
    }
}

public enum PatientAPIClientFactory {
    /// Creates the live transport from deployment supplied dependencies. Construction performs no request.
    public static func makeLive(configuration: LivePatientAPIClientConfiguration, session: URLSession = .shared) throws -> any PatientAPIClient {
        try URLSessionPatientAPIClient(baseURLProvider: configuration.baseURLProvider, tokenProvider: configuration.tokenProvider, requestIDProvider: configuration.requestIDProvider, session: session, retryPolicy: configuration.retryPolicy)
    }
}

/// URLSession transport for the frozen v0.2.0 contract.
/// Authentication, endpoint selection, and request IDs remain injectable for tests and deployment adapters.
public struct URLSessionPatientAPIClient: PatientAPIClient, Sendable {
    private let transport: any PatientAPITransport
    private let requestIDProvider: (any RequestIDProvider)?
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(
        baseURLProvider: any APIBaseURLProvider,
        tokenProvider: any BearerTokenProvider,
        requestIDProvider: any RequestIDProvider,
        session: URLSession = .shared,
        retryPolicy: PatientAPITransportRetryPolicy = PatientAPITransportRetryPolicy()
    ) throws {
        do {
            self.transport = try URLSessionPatientAPITransport(baseURLProvider: baseURLProvider, tokenProvider: tokenProvider, requestIDProvider: requestIDProvider, session: session, retryPolicy: retryPolicy)
        } catch PatientAPITransportError.invalidURL {
            throw PatientAPIClientError.invalidBaseURL
        } catch {
            throw PatientAPIClientError.invalidRequest
        }
        self.requestIDProvider = requestIDProvider
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    /// Initializes the typed client over a generated OpenAPI transport or a
    /// deterministic test double. Auth and URL policy remain outside this layer.
    public init(transport: any PatientAPITransport) {
        self.transport = transport
        self.requestIDProvider = nil
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    public func createImport(_ request: ImportRequest) async throws -> ImportTicket {
        guard let mediaType = request.mediaType, let sha256 = request.sha256 else {
            throw PatientAPIClientError.invalidRequest
        }
        let payload = DocumentCreatePayload(filename: request.fileName, mediaType: mediaType, sizeBytes: request.byteCount, sha256: sha256)
        let response: ContractDocumentPayload = try await send(path: "/v1/documents", method: "POST", body: payload, idempotent: true)
        let document = try response.domainValue()
        return ImportTicket(id: document.id, documentID: document.id, title: document.title)
    }

    public func createUploadSession(documentID: UUID, idempotencyKey: String?) async throws -> UploadSession {
        let response: ContractUploadSessionPayload = try await send(
            path: "/v1/documents/\(documentID.uuidString)/upload-sessions",
            method: "POST",
            body: EmptyBody(),
            idempotent: true,
            idempotencyKey: idempotencyKey
        )
        return response.domainValue()
    }

    public func uploadSessionContent(sessionID: UUID, content: Data) async throws -> UploadSession {
        let response: ContractUploadSessionPayload = try await sendRaw(
            path: "/v1/upload-sessions/\(sessionID.uuidString)/content",
            method: "PUT",
            body: content
        )
        return response.domainValue()
    }

    public func listDocuments() async throws -> [Document] {
        let response: [ContractDocumentPayload] = try await send(path: "/v1/documents", method: "GET", body: Optional<EmptyBody>.none, idempotent: false)
        return try response.map { try $0.domainValue() }
    }

    public func upload(_ request: UploadRequest) async throws -> UploadReceipt {
        let payload = ProcessingJobCreatePayload(jobType: .extractFacts)
        let response: ContractProcessingJobPayload = try await send(path: "/v1/documents/\(request.ticketID.uuidString)/processing-jobs", method: "POST", body: payload, idempotent: true)
        guard response.documentID == request.ticketID else { throw PatientAPIClientError.decoding }
        return UploadReceipt(id: response.id, ticketID: request.ticketID, documentID: response.documentID)
    }

    public func processingStatus(documentID: UUID) async throws -> ProcessingStatus {
        let response: ContractDocumentPayload = try await send(path: "/v1/documents/\(documentID.uuidString)", method: "GET", body: Optional<EmptyBody>.none, idempotent: false)
        switch response.status {
        case .uploaded: return .queued
        case .processing: return .processing
        case .ready: return .ready
        case .failed, .deleted: return .failed
        }
    }

    public func facts(documentID: UUID) async throws -> [Fact] {
        let response: [ContractFactPayload] = try await send(path: "/v1/facts", method: "GET", body: Optional<EmptyBody>.none, idempotent: false)
        return try response.filter { $0.documentID == documentID }.map { try $0.domainValue() }
    }

    public func editFact(_ command: FactEditCommand) async throws -> Fact {
        throw PatientAPIClientError.unsupported(.factEditNotInContract)
    }

    public func confirmFact(_ command: FactReviewCommand) async throws -> Fact {
        let payload = ContractReviewRequest(reviewStatus: .confirmed, ifMatchVersion: command.ifMatchVersion)
        let response: ContractFactPayload = try await send(path: "/v1/facts/\(command.factID.uuidString)/review", method: "POST", body: payload, ifMatchVersion: command.ifMatchVersion, idempotent: false)
        return try response.domainValue()
    }

    public func createTopic(_ request: TopicCreateRequest) async throws -> Topic {
        let payload = ContractTopicCreatePayload(name: request.name)
        let response: ContractTopicPayload = try await send(path: "/v1/topics", method: "POST", body: payload, idempotent: true)
        return try response.domainValue()
    }

    public func createVisit(_ request: VisitCreateRequest) async throws -> Visit {
        let payload = ContractVisitCreatePayload(title: request.title, startsAt: request.startsAt, topicIDs: request.topicIDs)
        let response: ContractVisitPayload = try await send(path: "/v1/visits", method: "POST", body: payload, idempotent: true, idempotencyKey: request.idempotencyKey)
        return try response.domainValue()
    }

    public func createTask(_ request: TaskCreateRequest) async throws -> Task {
        let payload = ContractTaskCreatePayload(title: request.title, visitID: request.visitID, dueAt: request.dueAt)
        let response: ContractTaskPayload = try await send(path: "/v1/tasks", method: "POST", body: payload, idempotent: true, idempotencyKey: request.idempotencyKey)
        return try response.domainValue()
    }

    public func listTopics() async throws -> [Topic] {
        let response: [ContractTopicPayload] = try await send(path: "/v1/topics", method: "GET", body: Optional<EmptyBody>.none, idempotent: false)
        return try response.map { try $0.domainValue() }
    }

    public func listVisits() async throws -> [Visit] {
        let response: [ContractVisitPayload] = try await send(path: "/v1/visits", method: "GET", body: Optional<EmptyBody>.none, idempotent: false)
        return try response.map { try $0.domainValue() }
    }

    public func listTasks() async throws -> [Task] {
        let response: [ContractTaskPayload] = try await send(path: "/v1/tasks", method: "GET", body: Optional<EmptyBody>.none, idempotent: false)
        return try response.map { try $0.domainValue() }
    }

    public func createShare(_ request: ShareCreateRequest) async throws -> ShareCreation {
        guard request.resourceVersion > 0, request.expiresAt > .now else { throw PatientAPIClientError.invalidRequest }
        let payload = ContractShareCreatePayload(resourceType: request.resourceType, resourceID: request.resourceID, resourceVersion: request.resourceVersion, expiresAt: request.expiresAt)
        let response: ContractShareCreateResponse = try await send(path: "/v1/shares", method: "POST", body: payload, idempotent: true, idempotencyKey: request.idempotencyKey)
        guard !response.token.isEmpty else { throw PatientAPIClientError.decoding }
        return ShareCreation(share: try response.share.domainValue(), token: response.token)
    }

    public func revokeShare(id: UUID) async throws -> ShareVersion {
        let response: ContractShareVersionPayload = try await send(path: "/v1/shares/\(id.uuidString)/revoke", method: "POST", body: Optional<EmptyBody>.none, idempotent: true)
        return try response.domainValue()
    }

    private func send<Response: Decodable, Body: Encodable>(
        path: String,
        method: String,
        body: Body?,
        ifMatchVersion: Int? = nil,
        idempotent: Bool,
        idempotencyKey: String? = nil
    ) async throws -> Response {
        var headers = [String: String]()
        if idempotent {
            let key = idempotencyKey ?? requestIDProvider?.requestID() ?? UUID().uuidString
            guard !key.isEmpty else { throw PatientAPIClientError.invalidRequest }
            headers["Idempotency-Key"] = key
        }
        if let ifMatchVersion {
            guard ifMatchVersion > 0 else { throw PatientAPIClientError.invalidRequest }
            headers["If-Match-Version"] = String(ifMatchVersion)
        }
        var bodyData: Data?
        if let body {
            do {
                bodyData = try encoder.encode(body)
            } catch {
                throw PatientAPIClientError.invalidRequest
            }
            headers["Content-Type"] = "application/json"
        }
        do {
            let response = try await transport.send(PatientAPITransportRequest(method: method, path: path, headers: headers, body: bodyData, idempotent: idempotent))
            guard (200..<300).contains(response.statusCode) else { throw map(statusCode: response.statusCode) }
            do {
                return try decoder.decode(Response.self, from: response.body)
            } catch {
                throw PatientAPIClientError.decoding
            }
        } catch let error as PatientAPIClientError {
            throw error
        } catch PatientAPITransportError.missingBearerToken {
            throw PatientAPIClientError.missingBearerToken
        } catch PatientAPITransportError.invalidURL {
            throw PatientAPIClientError.invalidBaseURL
        } catch PatientAPITransportError.invalidRequest {
            throw PatientAPIClientError.invalidRequest
        } catch {
            throw PatientAPIClientError.transport
        }
    }

    private func sendRaw<Response: Decodable>(
        path: String,
        method: String,
        body: Data
    ) async throws -> Response {
        let headers = ["Content-Type": "application/octet-stream"]
        do {
            let response = try await transport.send(
                PatientAPITransportRequest(method: method, path: path, headers: headers, body: body, idempotent: false)
            )
            guard (200..<300).contains(response.statusCode) else { throw map(statusCode: response.statusCode) }
            do {
                return try decoder.decode(Response.self, from: response.body)
            } catch {
                throw PatientAPIClientError.decoding
            }
        } catch let error as PatientAPIClientError {
            throw error
        } catch PatientAPITransportError.missingBearerToken {
            throw PatientAPIClientError.missingBearerToken
        } catch PatientAPITransportError.invalidURL {
            throw PatientAPIClientError.invalidBaseURL
        } catch PatientAPITransportError.invalidRequest {
            throw PatientAPIClientError.invalidRequest
        } catch {
            throw PatientAPIClientError.transport
        }
    }

    private func map(statusCode: Int) -> PatientAPIClientError {
        switch statusCode {
        case 401: .unauthorized
        case 403: .forbidden
        case 404: .notFound
        case 409: .versionConflict
        case 422: .validation
        case 500...599: .server(statusCode)
        default: .server(statusCode)
        }
    }
}

private struct DocumentCreatePayload: Encodable {
    let filename: String
    let mediaType: String
    let sizeBytes: Int
    let sha256: String

    enum CodingKeys: String, CodingKey {
        case filename, mediaType = "media_type", sizeBytes = "size_bytes", sha256
    }
}

private struct ProcessingJobCreatePayload: Encodable {
    let jobType: JobType

    enum CodingKeys: String, CodingKey {
        case jobType = "job_type"
    }
}

private struct EmptyBody: Encodable {}
