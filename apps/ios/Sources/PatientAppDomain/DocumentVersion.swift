import Foundation

/// A stable, display-ready version record built from the existing Document
/// contract. A future versions endpoint can replace the loader without changing
/// UI state or the rest of the import flow.
public struct DocumentVersion: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let documentID: UUID
    public let title: String
    public let state: LifecycleState
    public let processingStatus: DocumentProcessingStatus
    public let version: Int
    public let createdAt: Date
    public let updatedAt: Date

    public var id: String { "(documentID.uuidString)-v(version)" }

    public init(
        documentID: UUID,
        title: String,
        state: LifecycleState,
        processingStatus: DocumentProcessingStatus,
        version: Int,
        createdAt: Date,
        updatedAt: Date
    ) {
        self.documentID = documentID
        self.title = title
        self.state = state
        self.processingStatus = processingStatus
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    public init(document: Document) {
        self.init(
            documentID: document.id,
            title: document.title,
            state: document.state,
            processingStatus: document.processingStatus,
            version: document.version,
            createdAt: document.createdAt,
            updatedAt: document.updatedAt
        )
    }
}
