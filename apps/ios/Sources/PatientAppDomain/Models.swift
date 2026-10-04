import Foundation

public enum ContractDataIssue: Equatable, Sendable {
    case missingDocumentID
    case invalidVersion
    case missingSourceReference
    case unsupportedResourceType
}

public enum PatientAppError: Error, Equatable, Sendable {
    case unavailable
    case invalidInput
    case uploadFailed
    case processingFailed
    case processingTimeout
    case processingCancelled
    case factNotFound
    case versionConflict
    case invalidTransition(from: LifecycleState, to: LifecycleState)
    case reviewRequired
    case sourceRequired
    case invalidContractData(ContractDataIssue)
}

public enum UnsupportedOperation: Equatable, Sendable {
    case factEditNotInContract
    case topicCreationNotInClient
    case visitCreationNotInClient
    case taskCreationNotInClient
    case topicListingNotInClient
    case visitListingNotInClient
    case taskListingNotInClient
    case shareCreationNotInClient
    case shareRevocationNotInClient
    case shareStatusNotInClient
    case pdfExportNotInClient
    case uploadSessionCreationNotInClient
    case uploadContentNotInClient
    case documentListingNotInClient
}

public enum PatientAPIClientError: Error, Equatable, Sendable {
    case invalidBaseURL
    case missingBearerToken
    case invalidRequest
    case unsupported(UnsupportedOperation)
    case unauthorized
    case forbidden
    case notFound
    case versionConflict
    case validation
    case server(Int)
    case transport
    case decoding
    case shareExpired
    case shareRevoked
}

public enum SourceType: String, Codable, CaseIterable, Sendable {
    case uploadedDocument = "uploaded_document"
    case userInput = "user_input"
    case ocr
    case ehrImport = "ehr_import"
    case aiExtraction = "ai_extraction"
    case translation
    case other
}

public enum DocumentProcessingStatus: String, Codable, CaseIterable, Sendable {
    case uploaded
    case processing
    case ready
    case failed
    case deleted
}

public enum UploadSessionStatus: String, Codable, CaseIterable, Sendable {
    case pending
    case verified
}

public enum JobType: String, Codable, CaseIterable, Sendable {
    case ocr
    case extractFacts = "extract_facts"
    case translate
    case renderShare = "render_share"
}

public enum JobStatus: String, Codable, CaseIterable, Sendable {
    case queued
    case running
    case succeeded
    case failed
    case cancelled
}

public struct ProcessingJob: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let documentID: UUID
    public let type: JobType
    public var status: JobStatus
    public let attempt: Int
    public let errorCode: String?
    public let createdAt: Date
    public let updatedAt: Date

    public init(id: UUID, documentID: UUID, type: JobType, status: JobStatus, attempt: Int, errorCode: String?, createdAt: Date, updatedAt: Date) {
        self.id = id
        self.documentID = documentID
        self.type = type
        self.status = status
        self.attempt = attempt
        self.errorCode = errorCode
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }
}

public enum LifecycleState: String, Codable, CaseIterable, Sendable {
    case draft
    case needsReview = "needs_review"
    case confirmed
    case shared
    case revoked
    case archived

    public func canTransition(to next: LifecycleState) -> Bool {
        switch (self, next) {
        case (.draft, .needsReview), (.draft, .archived): true
        case (.needsReview, .confirmed), (.needsReview, .archived): true
        case (.confirmed, .shared), (.confirmed, .archived): true
        case (.shared, .revoked), (.shared, .archived): true
        case (.revoked, .archived): true
        default: false
        }
    }

    public var displayName: String {
        switch self {
        case .draft: "Draft"
        case .needsReview: "Needs review"
        case .confirmed: "Confirmed"
        case .shared: "Shared"
        case .revoked: "Revoked"
        case .archived: "Archived"
        }
    }
}

public struct SourceReference: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let documentID: UUID
    public let locator: String

    public init(id: UUID = UUID(), documentID: UUID, locator: String) {
        self.id = id
        self.documentID = documentID
        self.locator = locator
    }
}

public struct Document: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public var title: String
    public var state: LifecycleState
    public let createdAt: Date
    public var processingStatus: DocumentProcessingStatus
    public var version: Int
    public var updatedAt: Date
    public var deletedAt: Date?

    public init(id: UUID = UUID(), title: String, state: LifecycleState = .draft, createdAt: Date = .now, processingStatus: DocumentProcessingStatus = .uploaded, version: Int = 1, updatedAt: Date? = nil, deletedAt: Date? = nil) {
        self.id = id
        self.title = title
        self.state = state
        self.createdAt = createdAt
        self.processingStatus = processingStatus
        self.version = version
        self.updatedAt = updatedAt ?? createdAt
        self.deletedAt = deletedAt
    }

    public mutating func transition(to next: LifecycleState) throws {
        guard state.canTransition(to: next) else {
            throw PatientAppError.invalidTransition(from: state, to: next)
        }
        state = next
    }
}

public struct Topic: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public var name: String
    public var factIDs: [UUID]
    public var version: Int
    public let createdAt: Date
    public var updatedAt: Date

    public init(id: UUID = UUID(), name: String, factIDs: [UUID] = [], version: Int = 1, createdAt: Date = .now, updatedAt: Date? = nil) {
        self.id = id
        self.name = name
        self.factIDs = factIDs
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt ?? createdAt
    }
}

public struct Fact: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let documentID: UUID
    public let topicID: UUID?
    public var value: String
    public var sourceReference: SourceReference?
    public var isUserInput: Bool
    public var state: LifecycleState
    public var wasExplicitlyReviewed: Bool
    public var reviewStatus: ReviewStatus
    public var sourceType: SourceType
    public var confidence: Double?
    public var version: Int
    public let createdAt: Date
    public var updatedAt: Date

    public init(
        id: UUID = UUID(),
        documentID: UUID,
        topicID: UUID? = nil,
        value: String,
        sourceReference: SourceReference? = nil,
        isUserInput: Bool = false,
        state: LifecycleState = .draft,
        wasExplicitlyReviewed: Bool = false,
        reviewStatus: ReviewStatus = .unreviewed,
        sourceType: SourceType = .other,
        confidence: Double? = nil,
        version: Int = 1,
        createdAt: Date = .now,
        updatedAt: Date? = nil
    ) {
        self.id = id
        self.documentID = documentID
        self.topicID = topicID
        self.value = value
        self.sourceReference = sourceReference
        self.isUserInput = isUserInput
        self.state = state
        self.wasExplicitlyReviewed = wasExplicitlyReviewed
        self.reviewStatus = reviewStatus
        self.sourceType = sourceType
        self.confidence = confidence
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt ?? createdAt
    }

    public var isTraceable: Bool {
        (sourceReference?.documentID == documentID) || isUserInput
    }
    public var canAppearInDoctorView: Bool {
        isTraceable && state == .confirmed && wasExplicitlyReviewed && reviewStatus == .confirmed
    }

    public mutating func markNeedsReview() throws {
        try transition(to: .needsReview)
    }

    public mutating func confirmAfterExplicitReview() throws {
        guard isTraceable else { throw PatientAppError.sourceRequired }
        guard state == .needsReview else {
            throw PatientAppError.invalidTransition(from: state, to: .confirmed)
        }
        wasExplicitlyReviewed = true
        reviewStatus = .confirmed
        state = .confirmed
    }

    public mutating func transition(to next: LifecycleState) throws {
        guard state.canTransition(to: next) else {
            throw PatientAppError.invalidTransition(from: state, to: next)
        }
        if next == .confirmed { throw PatientAppError.reviewRequired }
        state = next
    }
}

public struct Visit: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public var title: String
    public var scheduledAt: Date?
    public var topicIDs: [UUID]
    public var state: LifecycleState
    public var version: Int
    public let createdAt: Date
    public var updatedAt: Date

    public init(id: UUID = UUID(), title: String, scheduledAt: Date? = nil, topicIDs: [UUID] = [], state: LifecycleState = .draft, version: Int = 1, createdAt: Date = .now, updatedAt: Date? = nil) {
        self.id = id
        self.title = title
        self.scheduledAt = scheduledAt
        self.topicIDs = topicIDs
        self.state = state
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt ?? createdAt
    }
}

public enum TaskStatus: String, Codable, CaseIterable, Sendable {
    case open
    case completed
    case cancelled
}

public struct Task: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public var title: String
    public var status: TaskStatus
    public let visitID: UUID?
    public let dueAt: Date?
    public var version: Int
    public let createdAt: Date
    public var updatedAt: Date

    public init(id: UUID = UUID(), title: String, status: TaskStatus = .open, visitID: UUID? = nil, dueAt: Date? = nil, version: Int = 1, createdAt: Date = .now, updatedAt: Date? = nil) {
        self.id = id
        self.title = title
        self.status = status
        self.visitID = visitID
        self.dueAt = dueAt
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt ?? createdAt
    }
}

public struct ShareVersion: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let documentID: UUID
    public let version: Int
    public let createdAt: Date
    public var state: LifecycleState
    public var revokedAt: Date?
    public var resourceType: SharedResourceType
    public var resourceID: UUID
    public var expiresAt: Date?

    public init(id: UUID = UUID(), documentID: UUID, version: Int, createdAt: Date = .now, state: LifecycleState = .shared, revokedAt: Date? = nil, resourceType: SharedResourceType = .document, resourceID: UUID? = nil, expiresAt: Date? = nil) {
        self.id = id
        self.documentID = documentID
        self.version = version
        self.createdAt = createdAt
        self.state = state
        self.revokedAt = revokedAt
        self.resourceType = resourceType
        self.resourceID = resourceID ?? documentID
        self.expiresAt = expiresAt
    }

    public mutating func revoke(at date: Date = .now) throws {
        guard state == .shared else {
            throw PatientAppError.invalidTransition(from: state, to: .revoked)
        }
        state = .revoked
        revokedAt = date
    }
}

public enum AuditAction: String, Codable, CaseIterable, Sendable {
    case created
    case markedNeedsReview = "marked_needs_review"
    case confirmed
    case shared
    case revoked
    case archived
}

public enum ReviewStatus: String, Codable, CaseIterable, Sendable {
    case unreviewed
    case inReview = "in_review"
    case confirmed
    case rejected
    case superseded
}

public enum SharedResourceType: String, Codable, CaseIterable, Sendable {
    case document
    case fact
    case topic
    case visit
    case task
}

public struct AuditEvent: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let entityID: UUID
    public let action: AuditAction
    public let occurredAt: Date

    public init(id: UUID = UUID(), entityID: UUID, action: AuditAction, occurredAt: Date = .now) {
        self.id = id
        self.entityID = entityID
        self.action = action
        self.occurredAt = occurredAt
    }
}

public enum LoadState<Value: Equatable & Sendable>: Equatable, Sendable {
    case idle
    case loading
    case empty
    case loaded(Value)
    case failed(PatientAppError)

    public var isRetryable: Bool {
        if case .failed = self { return true }
        return false
    }
}

public struct UploadSession: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let documentID: UUID
    public let documentVersion: Int
    public let sizeBytes: Int
    public let sha256: String
    public let mediaType: String
    public let expiresAt: Date
    public let createdAt: Date
    public var status: UploadSessionStatus
    public var verifiedAt: Date?

    public init(
        id: UUID = UUID(),
        documentID: UUID,
        documentVersion: Int = 1,
        sizeBytes: Int,
        sha256: String,
        mediaType: String,
        expiresAt: Date,
        createdAt: Date = .now,
        status: UploadSessionStatus = .pending,
        verifiedAt: Date? = nil
    ) {
        self.id = id
        self.documentID = documentID
        self.documentVersion = documentVersion
        self.sizeBytes = sizeBytes
        self.sha256 = sha256
        self.mediaType = mediaType
        self.expiresAt = expiresAt
        self.createdAt = createdAt
        self.status = status
        self.verifiedAt = verifiedAt
    }
}

public struct ImportRequest: Codable, Equatable, Hashable, Sendable {
    public let fileName: String
    public let title: String
    public let byteCount: Int
    public let mediaType: String?
    public let sha256: String?
    /// File bytes stay in memory for the upload-session handoff and are never persisted.
    public let content: Data?

    public init(fileName: String, title: String, byteCount: Int = 1, mediaType: String? = nil, sha256: String? = nil, content: Data? = nil) {
        self.fileName = fileName
        self.title = title
        self.byteCount = byteCount
        self.mediaType = mediaType
        self.sha256 = sha256
        self.content = content
    }
}

public struct ImportTicket: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let documentID: UUID
    public let title: String

    public init(id: UUID = UUID(), documentID: UUID, title: String) {
        self.id = id
        self.documentID = documentID
        self.title = title
    }
}

public struct UploadRequest: Codable, Equatable, Hashable, Sendable {
    public let ticketID: UUID
    public let byteCount: Int

    public init(ticketID: UUID, byteCount: Int) {
        self.ticketID = ticketID
        self.byteCount = byteCount
    }
}

public struct UploadReceipt: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let ticketID: UUID
    public let documentID: UUID

    public init(id: UUID = UUID(), ticketID: UUID, documentID: UUID) {
        self.id = id
        self.ticketID = ticketID
        self.documentID = documentID
    }
}

public enum ProcessingStatus: String, Codable, CaseIterable, Sendable {
    case queued
    case processing
    case ready
    case failed
}

public struct ImportSnapshot: Codable, Equatable, Hashable, Sendable {
    public let ticket: ImportTicket
    public let receipt: UploadReceipt
    public var status: ProcessingStatus
    public var facts: [Fact]

    public init(ticket: ImportTicket, receipt: UploadReceipt, status: ProcessingStatus, facts: [Fact] = []) {
        self.ticket = ticket
        self.receipt = receipt
        self.status = status
        self.facts = facts
    }
}

public enum ImportStage: Equatable, Sendable {
    case uploading
    case processing
    case loadingFacts
}

public enum ImportFlowState: Equatable, Sendable {
    case idle
    case uploading
    case processing
    case reviewRequired(ImportSnapshot)
    case empty(ImportSnapshot)
    case completed(ImportSnapshot)
    case failed(PatientAppError)
}

public struct FactEditCommand: Codable, Equatable, Hashable, Sendable {
    public let documentID: UUID
    public let factID: UUID
    public let value: String

    public init(documentID: UUID, factID: UUID, value: String) {
        self.documentID = documentID
        self.factID = factID
        self.value = value
    }
}

public struct FactReviewCommand: Codable, Equatable, Hashable, Sendable {
    public let documentID: UUID
    public let factID: UUID
    public let ifMatchVersion: Int

    public init(documentID: UUID, factID: UUID, ifMatchVersion: Int = 1) {
        self.documentID = documentID
        self.factID = factID
        self.ifMatchVersion = ifMatchVersion
    }
}
