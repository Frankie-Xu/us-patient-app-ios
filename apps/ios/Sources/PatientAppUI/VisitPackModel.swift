import Foundation
import PatientAppDomain

public enum VisitPackState: Equatable, Sendable {
    case idle
    case loading
    case loaded(VisitPack)
    case failed(PatientAPIClientError)

    public var isLoading: Bool {
        if case .loading = self { return true }
        return false
    }
}

/// Provides retryable preparation-pack state without coupling the UI to transport details.
@MainActor
public final class VisitPackModel: ObservableObject {
    @Published public private(set) var state: VisitPackState = .idle

    private let useCase: VisitPackUseCase
    private var loadedVisitID: UUID?

    public init(client: any PatientAPIClient) {
        self.useCase = VisitPackUseCase(client: client)
    }

    public var pack: VisitPack? {
        if case let .loaded(pack) = state { return pack }
        return nil
    }

    public var error: PatientAPIClientError? {
        if case let .failed(error) = state { return error }
        return nil
    }

    public func load(visitID: UUID) async {
        guard !state.isLoading else { return }
        loadedVisitID = visitID
        state = .loading
        do {
            state = .loaded(try await useCase.load(visitID: visitID))
        } catch let error as PatientAPIClientError {
            state = .failed(error)
        } catch {
            state = .failed(.transport)
        }
    }

    public func retry() async {
        guard let loadedVisitID, case .failed = state else { return }
        await load(visitID: loadedVisitID)
    }

    public func reset() {
        state = .idle
        loadedVisitID = nil
    }
}
