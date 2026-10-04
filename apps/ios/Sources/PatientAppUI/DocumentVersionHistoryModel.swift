import Foundation
import PatientAppDomain

public enum DocumentVersionHistoryState: Equatable, Sendable {
    case idle
    case loading
    case empty
    case loaded([DocumentVersion])
    case failed(PatientAPIClientError)

    public var versions: [DocumentVersion]? {
        if case let .loaded(value) = self { return value }
        return nil
    }

    public var error: PatientAPIClientError? {
        if case let .failed(value) = self { return value }
        return nil
    }
}

/// Loads version history through an injected seam. The default client adapter
/// uses the existing document listing contract and filters matching document
/// identifiers; a dedicated versions endpoint can be wired in later.
@MainActor
public final class DocumentVersionHistoryModel: ObservableObject {
    @Published public private(set) var state: DocumentVersionHistoryState = .idle

    private let loader: @Sendable (UUID) async throws -> [DocumentVersion]
    private var generation = 0
    private var lastDocumentID: UUID?

    public init(loader: @escaping @Sendable (UUID) async throws -> [DocumentVersion]) {
        self.loader = loader
    }

    public init(client: any PatientAPIClient) {
        self.loader = { documentID in
            let documents = try await client.listDocuments()
            return documents
                .filter { $0.id == documentID }
                .map(DocumentVersion.init(document:))
                .sorted { $0.version > $1.version }
        }
    }

    public func load(documentID: UUID) async {
        generation += 1
        let requestGeneration = generation
        lastDocumentID = documentID
        state = .loading
        do {
            let versions = try await loader(documentID)
            guard requestGeneration == generation else { return }
            state = versions.isEmpty ? .empty : .loaded(versions.sorted { $0.version > $1.version })
        } catch let error as PatientAPIClientError {
            guard requestGeneration == generation else { return }
            state = .failed(error)
        } catch {
            guard requestGeneration == generation else { return }
            state = .failed(.transport)
        }
    }

    public func retry() async {
        guard let lastDocumentID, case .failed = state else { return }
        await load(documentID: lastDocumentID)
    }

    public func invalidate() {
        generation += 1
        lastDocumentID = nil
        state = .idle
    }
}
