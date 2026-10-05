import Foundation
import PatientAppDomain
import SwiftUI

public enum ShareFlowState: Equatable, Sendable {
    case idle
    case creating
    case created(ShareCreation)
    case revoking(ShareCreation)
    case revoked(ShareVersion)
    case failed(PatientAPIClientError)

    public var isBusy: Bool {
        switch self {
        case .creating, .revoking: true
        default: false
        }
    }
}

/// Owns the user-visible create/share/revoke state for one visit share sheet.
@MainActor
public final class ShareFlowModel: ObservableObject {
    @Published public private(set) var state: ShareFlowState = .idle

    private let useCase: ShareUseCase
    private let client: any PatientAPIClient
    private let now: @Sendable () -> Date
    private var pendingRequest: ShareCreateRequest?
    private var activeCreation: ShareCreation?

    public init(
        client: any PatientAPIClient,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.client = client
        self.useCase = ShareUseCase(client: client)
        self.now = now
    }

    public var isBusy: Bool { state.isBusy }

    public var shareCreation: ShareCreation? {
        switch state {
        case let .created(creation), let .revoking(creation):
            return creation
        default:
            return activeCreation
        }
    }

    public var error: PatientAPIClientError? {
        if case let .failed(error) = state { return error }
        return nil
    }

    public func createVisitShare(for visit: Visit, expiresAt: Date? = nil) async {
        await createShare(
            resourceType: .visit,
            resourceID: visit.id,
            resourceVersion: visit.version,
            expiresAt: expiresAt
        )
    }

    public func createDocumentShare(documentID: UUID, version: Int, expiresAt: Date? = nil) async {
        await createShare(
            resourceType: .document,
            resourceID: documentID,
            resourceVersion: version,
            expiresAt: expiresAt
        )
    }

    public func exportPDF(documentID: UUID, version: Int) async throws -> PDFExportArtifact {
        try await PDFExportUseCase(client: client).export(documentID: documentID, documentVersion: version)
    }

    private func createShare(resourceType: SharedResourceType, resourceID: UUID, resourceVersion: Int, expiresAt: Date?) async {
        guard !isBusy else { return }
        let request = pendingRequest ?? ShareCreateRequest(
            resourceType: resourceType,
            resourceID: resourceID,
            resourceVersion: resourceVersion,
            expiresAt: expiresAt ?? now().addingTimeInterval(24 * 60 * 60),
            idempotencyKey: UUID().uuidString
        )
        pendingRequest = request
        state = .creating
        do {
            let creation = try await useCase.create(request, now: now)
            activeCreation = creation
            state = .created(creation)
        } catch {
            state = .failed(Self.map(error))
        }
    }

    public func retry() async {
        guard let pendingRequest, case .failed = state else { return }
        state = .creating
        do {
            let creation = try await useCase.create(pendingRequest, now: now)
            activeCreation = creation
            state = .created(creation)
        } catch {
            state = .failed(Self.map(error))
        }
    }

    public func revoke() async {
        guard let creation = shareCreation, !isBusy else { return }
        state = .revoking(creation)
        do {
            let revoked = try await useCase.revoke(id: creation.share.id)
            activeCreation = nil
            state = .revoked(revoked)
        } catch {
            state = .failed(Self.map(error))
        }
    }

    public func reset() {
        state = .idle
        pendingRequest = nil
        activeCreation = nil
    }

    private static func map(_ error: any Error) -> PatientAPIClientError {
        (error as? PatientAPIClientError) ?? .transport
    }
}
