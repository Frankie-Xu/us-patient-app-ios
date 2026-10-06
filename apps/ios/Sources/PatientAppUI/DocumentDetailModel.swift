import Foundation
import PatientAppDomain

public struct DocumentSourceLocation: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let documentID: UUID
    public let factID: UUID
    public let locator: String
    public let pageNumber: Int?

    public init(id: UUID = UUID(), documentID: UUID, factID: UUID, locator: String, pageNumber: Int? = nil) {
        self.id = id
        self.documentID = documentID
        self.factID = factID
        self.locator = locator
        self.pageNumber = pageNumber
    }

    public var displayLabel: String {
        if let pageNumber { return "Page \(pageNumber) · \(locator)" }
        return locator
    }

    public static func from(fact: Fact) -> DocumentSourceLocation? {
        guard let source = fact.sourceReference, source.documentID == fact.documentID else { return nil }
        let page = source.locator
            .split(separator: ":")
            .dropFirst()
            .first
            .flatMap { Int($0) }
        return DocumentSourceLocation(
            documentID: fact.documentID,
            factID: fact.id,
            locator: source.locator,
            pageNumber: page
        )
    }
}

public struct DocumentDetailPresentation: Equatable, Sendable {
    public let document: Document
    public let facts: [Fact]
    public let versions: [DocumentVersion]
    public let sourceLocations: [DocumentSourceLocation]

    public init(document: Document, facts: [Fact], versions: [DocumentVersion] = []) {
        self.document = document
        self.facts = facts
        self.versions = versions.isEmpty ? [DocumentVersion(document: document)] : versions.sorted { $0.version > $1.version }
        self.sourceLocations = facts.compactMap(DocumentSourceLocation.from(fact:))
    }
}

public enum DocumentDetailState: Equatable, Sendable {
    case idle
    case loading
    case loaded(DocumentDetailPresentation)
    case empty
    case failed(PatientAPIClientError)
}

@MainActor
public final class DocumentDetailModel: ObservableObject {
    @Published public private(set) var state: DocumentDetailState = .idle

    private let loader: @Sendable (UUID) async throws -> DocumentDetailPresentation
    private var generation = 0
    private var lastDocumentID: UUID?

    public init(loader: @escaping @Sendable (UUID) async throws -> DocumentDetailPresentation) {
        self.loader = loader
    }

    public init(client: any PatientAPIClient) {
        self.loader = { documentID in
            async let documents = client.listDocuments()
            async let facts = client.facts(documentID: documentID)
            guard let document = try await documents.first(where: { $0.id == documentID }) else {
                throw PatientAPIClientError.notFound
            }
            return DocumentDetailPresentation(document: document, facts: try await facts)
        }
    }

    public func load(documentID: UUID) async {
        generation += 1
        let requestGeneration = generation
        lastDocumentID = documentID
        state = .loading
        do {
            let detail = try await loader(documentID)
            guard requestGeneration == generation else { return }
            state = detail.facts.isEmpty ? .empty : .loaded(detail)
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
