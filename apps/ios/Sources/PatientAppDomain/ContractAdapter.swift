import Foundation

public enum ContractDocumentStatus: String, Codable, Sendable {
    case uploaded
    case processing
    case ready
    case failed
    case deleted
}

public enum ContractJobStatus: String, Codable, Sendable {
    case queued
    case running
    case succeeded
    case failed
    case cancelled
}

public enum ContractShareStatus: String, Codable, Sendable {
    case active
    case expired
    case revoked
}

public enum ContractTaskStatus: String, Codable, Sendable {
    case open
    case done
    case cancelled
}

public struct ContractTopicCreatePayload: Encodable, Equatable, Sendable {
    public let name: String
    public init(name: String) { self.name = name }
}

public struct ContractVisitCreatePayload: Encodable, Equatable, Sendable {
    public let title: String
    public let startsAt: Date?
    public let topicIDs: [UUID]

    public init(title: String, startsAt: Date?, topicIDs: [UUID]) {
        self.title = title
        self.startsAt = startsAt
        self.topicIDs = topicIDs
    }

    enum CodingKeys: String, CodingKey { case title, startsAt = "starts_at", topicIDs = "topic_ids" }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(title, forKey: .title)
        try container.encode(startsAt, forKey: .startsAt)
        try container.encode(topicIDs, forKey: .topicIDs)
    }
}

public struct ContractTaskCreatePayload: Encodable, Equatable, Sendable {
    public let title: String
    public let visitID: UUID?
    public let dueAt: Date?

    public init(title: String, visitID: UUID?, dueAt: Date?) {
        self.title = title
        self.visitID = visitID
        self.dueAt = dueAt
    }

    enum CodingKeys: String, CodingKey { case title, visitID = "visit_id", dueAt = "due_at" }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(title, forKey: .title)
        try container.encode(visitID, forKey: .visitID)
        try container.encode(dueAt, forKey: .dueAt)
    }
}

public struct ContractTopicPayload: Codable, Equatable, Sendable {
    public let name: String
    public let id: UUID
    public let ownerID: String
    public let version: Int
    public let createdAt: Date
    public let updatedAt: Date

    public init(name: String, id: UUID, ownerID: String, version: Int, createdAt: Date, updatedAt: Date) {
        self.name = name
        self.id = id
        self.ownerID = ownerID
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    enum CodingKeys: String, CodingKey { case name, id, ownerID = "owner_id", version, createdAt = "created_at", updatedAt = "updated_at" }
}

public struct ContractVisitPayload: Codable, Equatable, Sendable {
    public let title: String
    public let startsAt: Date?
    public let topicIDs: [UUID]
    public let id: UUID
    public let ownerID: String
    public let version: Int
    public let createdAt: Date
    public let updatedAt: Date

    public init(title: String, startsAt: Date?, topicIDs: [UUID], id: UUID, ownerID: String, version: Int, createdAt: Date, updatedAt: Date) {
        self.title = title
        self.startsAt = startsAt
        self.topicIDs = topicIDs
        self.id = id
        self.ownerID = ownerID
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    enum CodingKeys: String, CodingKey { case title, startsAt = "starts_at", topicIDs = "topic_ids", id, ownerID = "owner_id", version, createdAt = "created_at", updatedAt = "updated_at" }
}

public struct ContractTaskPayload: Codable, Equatable, Sendable {
    public let title: String
    public let visitID: UUID?
    public let dueAt: Date?
    public let id: UUID
    public let ownerID: String
    public let status: ContractTaskStatus
    public let version: Int
    public let createdAt: Date
    public let updatedAt: Date

    public init(title: String, visitID: UUID?, dueAt: Date?, id: UUID, ownerID: String, status: ContractTaskStatus, version: Int, createdAt: Date, updatedAt: Date) {
        self.title = title
        self.visitID = visitID
        self.dueAt = dueAt
        self.id = id
        self.ownerID = ownerID
        self.status = status
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    enum CodingKeys: String, CodingKey { case title, visitID = "visit_id", dueAt = "due_at", id, ownerID = "owner_id", status, version, createdAt = "created_at", updatedAt = "updated_at" }
}

public struct ContractDocumentPayload: Codable, Equatable, Sendable {
    public let filename: String
    public let mediaType: String
    public let sizeBytes: Int
    public let sha256: String
    public let id: UUID
    public let ownerID: String
    public let sourceType: SourceType
    public let status: ContractDocumentStatus
    public let version: Int
    public let createdAt: Date
    public let updatedAt: Date
    public let deletedAt: Date?

    public init(filename: String, mediaType: String, sizeBytes: Int, sha256: String, id: UUID, ownerID: String, sourceType: SourceType, status: ContractDocumentStatus, version: Int, createdAt: Date, updatedAt: Date, deletedAt: Date?) {
        self.filename = filename
        self.mediaType = mediaType
        self.sizeBytes = sizeBytes
        self.sha256 = sha256
        self.id = id
        self.ownerID = ownerID
        self.sourceType = sourceType
        self.status = status
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.deletedAt = deletedAt
    }

    enum CodingKeys: String, CodingKey {
        case filename, mediaType = "media_type", sizeBytes = "size_bytes", sha256, id, ownerID = "owner_id", sourceType = "source_type", status, version, createdAt = "created_at", updatedAt = "updated_at", deletedAt = "deleted_at"
    }
}

public struct ContractProcessingJobPayload: Codable, Equatable, Sendable {
    public let id: UUID
    public let ownerID: String
    public let documentID: UUID
    public let jobType: JobType
    public let status: ContractJobStatus
    public let idempotencyKey: String
    public let attempt: Int
    public let errorCode: String?
    public let createdAt: Date
    public let updatedAt: Date

    public init(id: UUID, ownerID: String, documentID: UUID, jobType: JobType, status: ContractJobStatus, idempotencyKey: String, attempt: Int, errorCode: String?, createdAt: Date, updatedAt: Date) {
        self.id = id
        self.ownerID = ownerID
        self.documentID = documentID
        self.jobType = jobType
        self.status = status
        self.idempotencyKey = idempotencyKey
        self.attempt = attempt
        self.errorCode = errorCode
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    enum CodingKeys: String, CodingKey {
        case id, ownerID = "owner_id", documentID = "document_id", jobType = "job_type", status, idempotencyKey = "idempotency_key", attempt, errorCode = "error_code", createdAt = "created_at", updatedAt = "updated_at"
    }
}

public struct ContractFactPayload: Codable, Equatable, Sendable {
    public let label: String
    public let value: String
    public let sourceRef: String?
    public let sourceType: SourceType
    public let confidence: Double
    public let documentID: UUID?
    public let topicID: UUID?
    public let id: UUID
    public let ownerID: String
    public let reviewStatus: ReviewStatus
    public let version: Int
    public let createdAt: Date
    public let updatedAt: Date

    public init(label: String, value: String, sourceRef: String?, sourceType: SourceType, confidence: Double, documentID: UUID?, topicID: UUID?, id: UUID, ownerID: String, reviewStatus: ReviewStatus, version: Int, createdAt: Date, updatedAt: Date) {
        self.label = label
        self.value = value
        self.sourceRef = sourceRef
        self.sourceType = sourceType
        self.confidence = confidence
        self.documentID = documentID
        self.topicID = topicID
        self.id = id
        self.ownerID = ownerID
        self.reviewStatus = reviewStatus
        self.version = version
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    enum CodingKeys: String, CodingKey {
        case label, value, sourceRef = "source_ref", sourceType = "source_type", confidence, documentID = "document_id", topicID = "topic_id", id, ownerID = "owner_id", reviewStatus = "review_status", version, createdAt = "created_at", updatedAt = "updated_at"
    }
}

public struct ContractReviewRequest: Encodable, Equatable, Sendable {
    public let reviewStatus: ReviewStatus
    public let ifMatchVersion: Int

    public init(reviewStatus: ReviewStatus, ifMatchVersion: Int) {
        self.reviewStatus = reviewStatus
        self.ifMatchVersion = ifMatchVersion
    }

    enum CodingKeys: String, CodingKey {
        case reviewStatus = "review_status"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(reviewStatus, forKey: .reviewStatus)
    }
}

public struct ContractShareVersionPayload: Codable, Equatable, Sendable {
    public let id: UUID
    public let ownerID: String
    public let resourceType: SharedResourceType
    public let resourceID: UUID
    public let resourceVersion: Int
    public let expiresAt: Date
    public let status: ContractShareStatus
    public let revokedAt: Date?
    public let createdAt: Date

    public init(id: UUID, ownerID: String, resourceType: SharedResourceType, resourceID: UUID, resourceVersion: Int, expiresAt: Date, status: ContractShareStatus, revokedAt: Date?, createdAt: Date) {
        self.id = id
        self.ownerID = ownerID
        self.resourceType = resourceType
        self.resourceID = resourceID
        self.resourceVersion = resourceVersion
        self.expiresAt = expiresAt
        self.status = status
        self.revokedAt = revokedAt
        self.createdAt = createdAt
    }

    enum CodingKeys: String, CodingKey {
        case id, ownerID = "owner_id", resourceType = "resource_type", resourceID = "resource_id", resourceVersion = "resource_version", expiresAt = "expires_at", status, revokedAt = "revoked_at", createdAt = "created_at"
    }
}

public extension ContractDocumentPayload {
    func domainValue() throws -> Document {
        guard version > 0 else { throw PatientAppError.invalidContractData(.invalidVersion) }
        return Document(
            id: id,
            title: filename,
            state: status == .deleted ? .archived : .draft,
            createdAt: createdAt,
            processingStatus: DocumentProcessingStatus(rawValue: status.rawValue) ?? .failed,
            version: version,
            updatedAt: updatedAt,
            deletedAt: deletedAt
        )
    }
}

public extension ContractProcessingJobPayload {
    func domainValue() throws -> ProcessingJob {
        guard attempt >= 0 else { throw PatientAppError.invalidContractData(.invalidVersion) }
        return ProcessingJob(id: id, documentID: documentID, type: jobType, status: JobStatus(rawValue: status.rawValue) ?? .failed, attempt: attempt, errorCode: errorCode, createdAt: createdAt, updatedAt: updatedAt)
    }
}

public extension ContractFactPayload {
    func domainValue() throws -> Fact {
        guard let documentID else { throw PatientAppError.invalidContractData(.missingDocumentID) }
        guard version > 0 else { throw PatientAppError.invalidContractData(.invalidVersion) }
        let sourceReference: SourceReference?
        if let sourceRef, !sourceRef.isEmpty {
            sourceReference = SourceReference(documentID: documentID, locator: sourceRef)
        } else {
            sourceReference = nil
        }
        if reviewStatus == .confirmed && sourceReference == nil {
            throw PatientAppError.invalidContractData(.missingSourceReference)
        }
        let state: LifecycleState = switch reviewStatus {
        case .unreviewed, .inReview: .needsReview
        case .confirmed: .confirmed
        case .rejected, .superseded: .archived
        }
        return Fact(id: id, documentID: documentID, topicID: topicID, value: value, sourceReference: sourceReference, isUserInput: sourceType == .userInput, state: state, wasExplicitlyReviewed: reviewStatus == .confirmed, reviewStatus: reviewStatus, sourceType: sourceType, confidence: confidence, version: version, createdAt: createdAt, updatedAt: updatedAt)
    }
}

public extension ContractReviewRequest {
    func domainCommand(documentID: UUID, factID: UUID) throws -> FactReviewCommand {
        guard reviewStatus == .confirmed else { throw PatientAppError.reviewRequired }
        guard ifMatchVersion > 0 else { throw PatientAppError.invalidContractData(.invalidVersion) }
        return FactReviewCommand(documentID: documentID, factID: factID, ifMatchVersion: ifMatchVersion)
    }
}

public extension ContractShareVersionPayload {
    func domainValue() throws -> ShareVersion {
        guard resourceVersion > 0 else { throw PatientAppError.invalidContractData(.invalidVersion) }
        let state: LifecycleState = switch status {
        case .active: .shared
        case .expired: .archived
        case .revoked: .revoked
        }
        return ShareVersion(id: id, documentID: resourceID, version: resourceVersion, createdAt: createdAt, state: state, revokedAt: revokedAt, resourceType: resourceType, resourceID: resourceID, expiresAt: expiresAt)
    }
}

public extension ContractTopicPayload {
    func domainValue() throws -> Topic {
        guard version > 0 else { throw PatientAppError.invalidContractData(.invalidVersion) }
        return Topic(id: id, name: name, version: version, createdAt: createdAt, updatedAt: updatedAt)
    }
}

public extension ContractVisitPayload {
    func domainValue() throws -> Visit {
        guard version > 0 else { throw PatientAppError.invalidContractData(.invalidVersion) }
        return Visit(id: id, title: title, scheduledAt: startsAt, topicIDs: topicIDs, version: version, createdAt: createdAt, updatedAt: updatedAt)
    }
}

public extension ContractTaskPayload {
    func domainValue() throws -> Task {
        guard version > 0 else { throw PatientAppError.invalidContractData(.invalidVersion) }
        let status: TaskStatus = switch status {
        case .open: .open
        case .done: .completed
        case .cancelled: .cancelled
        }
        return Task(id: id, title: title, status: status, visitID: visitID, dueAt: dueAt, version: version, createdAt: createdAt, updatedAt: updatedAt)
    }
}
