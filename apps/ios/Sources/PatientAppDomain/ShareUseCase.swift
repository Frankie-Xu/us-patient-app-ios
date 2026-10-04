import Foundation

/// Validates and delegates version-pinned share operations to the replaceable API client.
public struct ShareUseCase: Sendable {
    private let client: any PatientAPIClient

    public init(client: any PatientAPIClient) {
        self.client = client
    }

    public func create(
        _ request: ShareCreateRequest,
        now: @escaping @Sendable () -> Date = { Date() }
    ) async throws -> ShareCreation {
        guard request.resourceVersion > 0, request.expiresAt > now() else {
            throw PatientAPIClientError.invalidRequest
        }
        return try await client.createShare(request)
    }

    public func revoke(id: UUID) async throws -> ShareVersion {
        try await client.revokeShare(id: id)
    }
}
