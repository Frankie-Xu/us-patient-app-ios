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

/// The independently refreshed access state for a share token.
///
/// Creation/revocation and status lookup have different retry semantics. Keeping
/// this state separate lets the UI retain a usable token when a status request
/// is temporarily unavailable.
public enum ShareStatusState: Equatable, Sendable {
    case idle
    case refreshing
    case loaded(ShareAccessStatus)
    case failed(PatientAPIClientError)

    public var isBusy: Bool {
        if case .refreshing = self { return true }
        return false
    }
}

/// Owns the user-visible create/share/revoke state for one visit share sheet.
@MainActor
public final class ShareFlowModel: ObservableObject {
    @Published public private(set) var state: ShareFlowState = .idle
    @Published public private(set) var statusState: ShareStatusState = .idle

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

    public var isRefreshingStatus: Bool { statusState.isBusy }

    public var accessStatus: ShareAccessStatus? {
        if case let .loaded(status) = statusState { return status }
        return nil
    }

    public var statusError: PatientAPIClientError? {
        if case let .failed(error) = statusState { return error }
        return nil
    }

    /// Short, stable copy for status badges and accessibility labels.
    public var statusLabel: String {
        switch statusState {
        case .idle: return "Status not checked"
        case .refreshing: return "Checking access"
        case .loaded(let status):
            switch status.state {
            case .active: return "Active"
            case .expired: return "Expired"
            case .revoked: return "Revoked"
            }
        case .failed: return "Status unavailable"
        }
    }

    public var statusMessage: String {
        switch statusState {
        case .idle: return "Access status has not been checked yet."
        case .refreshing: return "Checking whether this share link can still be opened."
        case .loaded(let status):
            switch status.state {
            case .active: return "This share link is active."
            case .expired: return "This share link has expired."
            case .revoked: return "This share link has been revoked."
            }
        case .failed: return "Access status could not be refreshed. Try again."
        }
    }

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
            await refreshStatus()
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
            await refreshStatus()
        } catch {
            state = .failed(Self.map(error))
        }
    }

    /// Refreshes the server-reported state for the current share token.
    ///
    /// A failed lookup leaves the token and creation state intact so callers can
    /// retry without creating a second share or changing the idempotency key.
    public func refreshStatus() async {
        guard let creation = shareCreation, !isRefreshingStatus else { return }
        statusState = .refreshing
        do {
            let status = try await useCase.status(id: creation.share.id)
            statusState = .loaded(status)
        } catch {
            statusState = .failed(Self.map(error))
        }
    }

    public func retryStatus() async {
        guard case .failed = statusState else { return }
        await refreshStatus()
    }

    public func revoke() async {
        guard let creation = shareCreation, !isBusy else { return }
        state = .revoking(creation)
        do {
            let revoked = try await useCase.revoke(id: creation.share.id)
            activeCreation = nil
            state = .revoked(revoked)
            statusState = .loaded(ShareAccessStatus(share: revoked, state: .revoked))
        } catch {
            state = .failed(Self.map(error))
        }
    }

    public func reset() {
        state = .idle
        statusState = .idle
        pendingRequest = nil
        activeCreation = nil
    }

    private static func map(_ error: any Error) -> PatientAPIClientError {
        (error as? PatientAPIClientError) ?? .transport
    }
}
