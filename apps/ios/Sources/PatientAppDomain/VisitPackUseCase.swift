import Foundation

/// Loads the server-owned preparation pack for one versioned visit.
public struct VisitPackUseCase: Sendable {
    private let client: any PatientAPIClient

    public init(client: any PatientAPIClient) {
        self.client = client
    }

    public func load(visitID: UUID) async throws -> VisitPack {
        try await client.visitPack(visitID: visitID)
    }
}
