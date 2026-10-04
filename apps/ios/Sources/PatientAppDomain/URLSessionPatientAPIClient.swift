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

/// URLSession transport for the frozen v0.2.0 contract.
/// Authentication, endpoint selection, and request IDs remain injectable for tests and deployment adapters.
public struct URLSessionPatientAPIClient: PatientAPIClient, Sendable {
    private let baseURLProvider: any APIBaseURLProvider
    private let tokenProvider: any BearerTokenProvider
    private let requestIDProvider: any RequestIDProvider
    private let session: URLSession
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(
        baseURLProvider: any APIBaseURLProvider,
        tokenProvider: any BearerTokenProvider,
        requestIDProvider: any RequestIDProvider,
        session: URLSession = .shared
    ) throws {
        guard baseURLProvider.baseURL.scheme != nil, baseURLProvider.baseURL.host != nil else {
            throw PatientAPIClientError.invalidBaseURL
        }
        self.baseURLProvider = baseURLProvider
        self.tokenProvider = tokenProvider
        self.requestIDProvider = requestIDProvider
        self.session = session
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

    private func send<Response: Decodable, Body: Encodable>(
        path: String,
        method: String,
        body: Body?,
        ifMatchVersion: Int? = nil,
        idempotent: Bool
    ) async throws -> Response {
        guard let url = URL(string: path, relativeTo: baseURLProvider.baseURL)?.absoluteURL else {
            throw PatientAPIClientError.invalidBaseURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let requestID = requestIDProvider.requestID()
        guard !requestID.isEmpty else { throw PatientAPIClientError.invalidRequest }
        request.setValue(requestID, forHTTPHeaderField: "X-Request-ID")
        if idempotent { request.setValue(requestID, forHTTPHeaderField: "Idempotency-Key") }
        if let ifMatchVersion {
            guard ifMatchVersion > 0 else { throw PatientAPIClientError.invalidRequest }
            request.setValue(String(ifMatchVersion), forHTTPHeaderField: "If-Match-Version")
        }
        guard let token = try await tokenProvider.bearerToken(), !token.isEmpty else {
            throw PatientAPIClientError.missingBearerToken
        }
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            do {
                request.httpBody = try encoder.encode(body)
            } catch {
                throw PatientAPIClientError.invalidRequest
            }
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw PatientAPIClientError.transport
        }
        guard let http = response as? HTTPURLResponse else { throw PatientAPIClientError.transport }
        guard (200..<300).contains(http.statusCode) else { throw map(statusCode: http.statusCode) }
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw PatientAPIClientError.decoding
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
