import Foundation

public enum PatientAppError: Error, Equatable, Sendable {
    case unavailable
    case invalidInput
    case uploadFailed
    case processingFailed
    case factNotFound
    case invalidTransition(from: LifecycleState, to: LifecycleState)
    case reviewRequired
    case sourceRequired
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

    public init(id: UUID = UUID(), title: String, state: LifecycleState = .draft, createdAt: Date = .now) {
        self.id = id
        self.title = title
        self.state = state
        self.createdAt = createdAt
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

    public init(id: UUID = UUID(), name: String, factIDs: [UUID] = []) {
        self.id = id
        self.name = name
        self.factIDs = factIDs
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

    public init(
        id: UUID = UUID(),
        documentID: UUID,
        topicID: UUID? = nil,
        value: String,
        sourceReference: SourceReference? = nil,
        isUserInput: Bool = false,
        state: LifecycleState = .draft,
        wasExplicitlyReviewed: Bool = false
    ) {
        self.id = id
        self.documentID = documentID
        self.topicID = topicID
        self.value = value
        self.sourceReference = sourceReference
        self.isUserInput = isUserInput
        self.state = state
        self.wasExplicitlyReviewed = wasExplicitlyReviewed
    }

    public var isTraceable: Bool {
        (sourceReference?.documentID == documentID) || isUserInput
    }
    public var canAppearInDoctorView: Bool {
        isTraceable && state == .confirmed && wasExplicitlyReviewed
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

    public init(id: UUID = UUID(), title: String, scheduledAt: Date? = nil, topicIDs: [UUID] = [], state: LifecycleState = .draft) {
        self.id = id
        self.title = title
        self.scheduledAt = scheduledAt
        self.topicIDs = topicIDs
        self.state = state
    }
}

public enum TaskStatus: String, Codable, CaseIterable, Sendable {
    case open
    case completed
}

public struct Task: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public var title: String
    public var status: TaskStatus
    public let createdAt: Date

    public init(id: UUID = UUID(), title: String, status: TaskStatus = .open, createdAt: Date = .now) {
        self.id = id
        self.title = title
        self.status = status
        self.createdAt = createdAt
    }
}

public struct ShareVersion: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let id: UUID
    public let documentID: UUID
    public let version: Int
    public let createdAt: Date
    public var state: LifecycleState
    public var revokedAt: Date?

    public init(id: UUID = UUID(), documentID: UUID, version: Int, createdAt: Date = .now, state: LifecycleState = .shared, revokedAt: Date? = nil) {
        self.id = id
        self.documentID = documentID
        self.version = version
        self.createdAt = createdAt
        self.state = state
        self.revokedAt = revokedAt
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

public struct ImportRequest: Codable, Equatable, Hashable, Sendable {
    public let fileName: String
    public let title: String
    public let byteCount: Int

    public init(fileName: String, title: String, byteCount: Int = 1) {
        self.fileName = fileName
        self.title = title
        self.byteCount = byteCount
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

    public init(documentID: UUID, factID: UUID) {
        self.documentID = documentID
        self.factID = factID
    }
}
