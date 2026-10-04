import Foundation
import PatientAppDomain

public enum AccountHistoryState: Equatable, Sendable {
    case idle
    case loading
    case empty
    case loaded(AccountHistorySnapshot)
    case failed(PatientAPIClientError)

    public var isLoading: Bool { if case .loading = self { true } else { false } }
    public var snapshot: AccountHistorySnapshot? { if case let .loaded(value) = self { value } else { nil } }
    public var error: PatientAPIClientError? { if case let .failed(value) = self { value } else { nil } }
}

/// Loads account-owned history through a replaceable repository. A generation
/// token prevents a slower, older request from overwriting a newer session.
@MainActor
public final class AccountHistoryModel: ObservableObject {
    @Published public private(set) var state: AccountHistoryState = .idle

    private let useCase: AccountHistoryUseCase
    private var generation = 0

    public init(client: any PatientAPIClient) { useCase = AccountHistoryUseCase(client: client) }
    public init(repository: any AccountHistoryRepository) { useCase = AccountHistoryUseCase(repository: repository) }

    public func load() async {
        generation += 1
        let requestGeneration = generation
        state = .loading

        do {
            let snapshot = try await useCase.load()
            guard requestGeneration == generation else { return }
            state = snapshot.isEmpty ? .empty : .loaded(snapshot)
        } catch {
            guard requestGeneration == generation else { return }
            state = .failed(Self.clientError(for: error))
        }
    }

    public func retry() async {
        guard case .failed = state else { return }
        await load()
    }

    private static func clientError(for error: any Error) -> PatientAPIClientError {
        if let error = error as? PatientAPIClientError { return error }
        return .transport
    }
}
