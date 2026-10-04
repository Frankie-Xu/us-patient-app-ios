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
    private let cache: (any ProtectedCache)?
    private let sessionStore: (any SessionStore)?
    private var generation = 0

    public init(client: any PatientAPIClient, cache: (any ProtectedCache)? = nil, sessionStore: (any SessionStore)? = nil) {
        useCase = AccountHistoryUseCase(client: client)
        self.cache = cache
        self.sessionStore = sessionStore
    }

    public init(repository: any AccountHistoryRepository, cache: (any ProtectedCache)? = nil, sessionStore: (any SessionStore)? = nil) {
        useCase = AccountHistoryUseCase(repository: repository)
        self.cache = cache
        self.sessionStore = sessionStore
    }

    public func load() async {
        generation += 1
        let requestGeneration = generation
        state = .loading
        let session = await sessionStore?.currentSession()
        var restoredFromCache = false

        if let session, let cached = await cachedSnapshot(for: session) {
            guard await isCurrent(requestGeneration, session: session) else {
                if requestGeneration == generation { state = .idle }
                return
            }
            state = cached.isEmpty ? .empty : .loaded(cached)
            restoredFromCache = true
        }

        do {
            let snapshot = try await useCase.load()
            guard await isCurrent(requestGeneration, session: session) else {
                if requestGeneration == generation { state = .idle }
                return
            }
            state = snapshot.isEmpty ? .empty : .loaded(snapshot)
            if let session { await store(snapshot: snapshot, for: session) }
        } catch {
            guard await isCurrent(requestGeneration, session: session) else {
                if requestGeneration == generation { state = .idle }
                return
            }
            if !restoredFromCache { state = .failed(Self.clientError(for: error)) }
        }
    }

    public func retry() async {
        guard case .failed = state else { return }
        await load()
    }

    public func logout() async {
        invalidateSession()
        await sessionStore?.logout()
        await cache?.purgeAll()
    }

    public func invalidateSession() {
        generation += 1
        state = .idle
    }

    private func isCurrent(_ requestGeneration: Int, session: SessionContext?) async -> Bool {
        guard requestGeneration == generation else { return false }
        guard let session else { return true }
        guard let sessionStore else { return false }
        return await sessionStore.isCurrent(session)
    }

    private func cachedSnapshot(for session: SessionContext) async -> AccountHistorySnapshot? {
        guard let data = await cache?.data(forKey: Self.cacheKey, session: session) else { return nil }
        return try? JSONDecoder().decode(AccountHistorySnapshot.self, from: data)
    }

    private func store(snapshot: AccountHistorySnapshot, for session: SessionContext) async {
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        await cache?.setData(data, forKey: Self.cacheKey, session: session)
    }

    private static let cacheKey = "account-history-v1"

    private static func clientError(for error: any Error) -> PatientAPIClientError {
        if let error = error as? PatientAPIClientError { return error }
        return .transport
    }
}
