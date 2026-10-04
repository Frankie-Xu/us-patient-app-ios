import Foundation
import PatientAppDomain

public enum DocumentHistoryState: Equatable, Sendable {
    case idle
    case loading
    case empty
    case loaded([Document])
    case failed(PatientAPIClientError)

    public var documents: [Document]? {
        if case let .loaded(value) = self { return value }
        return nil
    }

    public var error: PatientAPIClientError? {
        if case let .failed(value) = self { return value }
        return nil
    }
}

@MainActor
public final class DocumentHistoryModel: ObservableObject {
    @Published public private(set) var state: DocumentHistoryState = .idle

    private let client: any PatientAPIClient
    private var generation = 0

    public init(client: any PatientAPIClient) {
        self.client = client
    }

    public func load() async {
        generation += 1
        let requestGeneration = generation
        state = .loading

        do {
            let documents = try await client.listDocuments()
            guard requestGeneration == generation else { return }
            let sorted = documents.sorted { $0.updatedAt > $1.updatedAt }
            state = sorted.isEmpty ? .empty : .loaded(sorted)
        } catch {
            guard requestGeneration == generation else { return }
            state = .failed(error as? PatientAPIClientError ?? .transport)
        }
    }

    public func retry() async {
        guard case .failed = state else { return }
        await load()
    }

    public func invalidateSession() {
        generation += 1
        state = .idle
    }
}
