import Foundation

/// Server-reported access state for a version-pinned share.
public enum ShareAccessState: String, Codable, CaseIterable, Sendable {
    case active
    case expired
    case revoked
}

/// A share status together with the immutable version and resource it protects.
public struct ShareAccessStatus: Codable, Equatable, Hashable, Sendable {
    public let share: ShareVersion
    public let state: ShareAccessState

    public init(share: ShareVersion, state: ShareAccessState) {
        self.share = share
        self.state = state
    }

    public var isAccessible: Bool { state == .active }
}

/// The server response for a deterministic, version-pinned PDF export.
public struct PDFExportArtifact: Equatable, Hashable, Sendable {
    public let data: Data
    public let contentType: String
    public let documentVersion: Int
    public let sha256: String

    public init(data: Data, contentType: String, documentVersion: Int, sha256: String) {
        self.data = data
        self.contentType = contentType
        self.documentVersion = documentVersion
        self.sha256 = sha256
    }
}

public extension ContractShareVersionPayload {
    func accessStatus() throws -> ShareAccessStatus {
        guard resourceVersion > 0 else {
            throw PatientAppError.invalidContractData(.invalidVersion)
        }
        let state: ShareAccessState
        let lifecycleState: LifecycleState
        switch status {
        case .active:
            state = .active
            lifecycleState = .shared
        case .expired:
            state = .expired
            lifecycleState = .shared
        case .revoked:
            state = .revoked
            lifecycleState = .revoked
        }
        let share = ShareVersion(
            id: id,
            documentID: resourceID,
            version: resourceVersion,
            createdAt: createdAt,
            state: lifecycleState,
            revokedAt: revokedAt,
            resourceType: resourceType,
            resourceID: resourceID,
            expiresAt: expiresAt
        )
        return ShareAccessStatus(share: share, state: state)
    }
}

/// PDF export remains separate from ShareUseCase so share lifecycle and binary
/// response handling can evolve independently.
public struct PDFExportUseCase: Sendable {
    private let client: any PatientAPIClient

    public init(client: any PatientAPIClient) {
        self.client = client
    }

    public func export(documentID: UUID, documentVersion: Int) async throws -> PDFExportArtifact {
        guard documentVersion > 0 else {
            throw PatientAPIClientError.invalidRequest
        }
        return try await client.exportPDF(documentID: documentID, documentVersion: documentVersion)
    }
}
