import Foundation

/// A provider-neutral request passed from the typed client to its transport.
/// The transport owns URL construction and authorization injection; callers never
/// parse or persist bearer tokens.
public struct PatientAPITransportRequest: Equatable, Sendable {
    public let method: String
    public let path: String
    public let headers: [String: String]
    public let body: Data?
    public let idempotent: Bool

    public init(method: String, path: String, headers: [String: String] = [:], body: Data? = nil, idempotent: Bool = false) {
        self.method = method
        self.path = path
        self.headers = headers
        self.body = body
        self.idempotent = idempotent
    }
}

public struct PatientAPITransportResponse: Equatable, Sendable {
    public let statusCode: Int
    public let headers: [String: String]
    public let body: Data

    public init(statusCode: Int, headers: [String: String] = [:], body: Data = Data()) {
        self.statusCode = statusCode
        self.headers = headers
        self.body = body
    }
}

public enum PatientAPITransportError: Error, Equatable, Sendable {
    case invalidURL
    case invalidRequest
    case missingBearerToken
    case transport
}

public protocol PatientAPITransport: Sendable {
    func send(_ request: PatientAPITransportRequest) async throws -> PatientAPITransportResponse
}

/// Retry is deliberately limited to idempotent requests. This keeps a network
/// timeout from duplicating a visit/task/share write that has no server-side
/// idempotency key.
public struct PatientAPITransportRetryPolicy: Equatable, Sendable {
    public let maxAttempts: Int
    public let baseDelay: Duration

    public init(maxAttempts: Int = 3, baseDelay: Duration = .milliseconds(50)) {
        self.maxAttempts = max(1, maxAttempts)
        self.baseDelay = baseDelay
    }

    public func shouldRetry(request: PatientAPITransportRequest, statusCode: Int? = nil) -> Bool {
        guard request.idempotent else { return false }
        if let statusCode {
            return statusCode == 408 || statusCode == 429 || (500...599).contains(statusCode)
        }
        return true
    }

    public func delay(forAttempt attempt: Int) -> Duration {
        guard attempt > 0 else { return .zero }
        let multiplier = 1 << min(attempt - 1, 5)
        return baseDelay * multiplier
    }
}

/// The URLSession implementation is the replaceable seam for a generated
/// OpenAPI transport. It adds request IDs and bearer authorization consistently,
/// then applies bounded retries to idempotent reads and writes with keys.
public struct URLSessionPatientAPITransport: PatientAPITransport, Sendable {
    private let baseURLProvider: any APIBaseURLProvider
    private let tokenProvider: any BearerTokenProvider
    private let requestIDProvider: any RequestIDProvider
    private let session: URLSession
    private let retryPolicy: PatientAPITransportRetryPolicy
    /// The sleeper is throwing so task cancellation cannot be swallowed and
    /// accidentally turn into another network attempt.
    private let sleeper: @Sendable (Duration) async throws -> Void

    public init(
        baseURLProvider: any APIBaseURLProvider,
        tokenProvider: any BearerTokenProvider,
        requestIDProvider: any RequestIDProvider,
        session: URLSession = .shared,
        retryPolicy: PatientAPITransportRetryPolicy = PatientAPITransportRetryPolicy(),
        sleeper: @escaping @Sendable (Duration) async throws -> Void = { duration in
            guard duration > .zero else { return }
            try await _Concurrency.Task.sleep(for: duration)
        }
    ) throws {
        guard baseURLProvider.baseURL.scheme != nil, baseURLProvider.baseURL.host != nil else {
            throw PatientAPITransportError.invalidURL
        }
        self.baseURLProvider = baseURLProvider
        self.tokenProvider = tokenProvider
        self.requestIDProvider = requestIDProvider
        self.session = session
        self.retryPolicy = retryPolicy
        self.sleeper = sleeper
    }

    public func send(_ request: PatientAPITransportRequest) async throws -> PatientAPITransportResponse {
        guard !request.method.isEmpty, !request.path.isEmpty else { throw PatientAPITransportError.invalidRequest }
        guard let url = URL(string: request.path, relativeTo: baseURLProvider.baseURL)?.absoluteURL else {
            throw PatientAPITransportError.invalidURL
        }
        let requestID = requestIDProvider.requestID()
        guard !requestID.isEmpty else { throw PatientAPITransportError.invalidRequest }
        guard let token = try await tokenProvider.bearerToken(), !token.isEmpty else {
            throw PatientAPITransportError.missingBearerToken
        }

        var attempt = 0
        while true {
            var urlRequest = URLRequest(url: url)
            urlRequest.httpMethod = request.method
            urlRequest.httpBody = request.body
            urlRequest.setValue("application/json", forHTTPHeaderField: "Accept")
            urlRequest.setValue(requestID, forHTTPHeaderField: "X-Request-ID")
            urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            for (name, value) in request.headers { urlRequest.setValue(value, forHTTPHeaderField: name) }

            let response: PatientAPITransportResponse
            do {
                let (data, rawResponse) = try await session.data(for: urlRequest)
                guard let http = rawResponse as? HTTPURLResponse else { throw PatientAPITransportError.transport }
                let headers = http.allHeaderFields.reduce(into: [String: String]()) { result, item in
                    if let key = item.key as? String { result[key] = String(describing: item.value) }
                }
                response = PatientAPITransportResponse(statusCode: http.statusCode, headers: headers, body: data)
            } catch is CancellationError {
                throw CancellationError()
            } catch let error as PatientAPITransportError {
                if Task.isCancelled { throw CancellationError() }
                if attempt + 1 >= retryPolicy.maxAttempts || !retryPolicy.shouldRetry(request: request) { throw error }
                attempt += 1
                try await sleeper(retryPolicy.delay(forAttempt: attempt))
                continue
            } catch {
                if Task.isCancelled { throw CancellationError() }
                if attempt + 1 >= retryPolicy.maxAttempts || !retryPolicy.shouldRetry(request: request) {
                    throw PatientAPITransportError.transport
                }
                attempt += 1
                try await sleeper(retryPolicy.delay(forAttempt: attempt))
                continue
            }

            if Task.isCancelled { throw CancellationError() }
            if attempt + 1 < retryPolicy.maxAttempts, retryPolicy.shouldRetry(request: request, statusCode: response.statusCode) {
                attempt += 1
                try await sleeper(retryPolicy.delay(forAttempt: attempt))
                continue
            }
            return response
        }
    }
}
