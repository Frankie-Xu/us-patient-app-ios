import Foundation

public enum MockFailurePoint: Equatable, Sendable {
    case createImport
    case upload
    case createUploadSession
    case uploadSessionContent
    case listDocuments
    case processingStatus
    case facts
    case editFact
    case confirmFact
    case listTopics
    case listVisits
    case listTasks
    case createShare
    case revokeShare
    case shareStatus
    case exportPDF
}

public struct MockImportScenario: Sendable {
    public let documentID: UUID
    public let facts: [Fact]
    public let pollsBeforeReady: Int
    public let terminalProcessingStatus: ProcessingStatus?
    public let failurePoint: MockFailurePoint?
    public let failuresRemaining: Int
    public let topics: [Topic]
    public let visits: [Visit]
    public let tasks: [Task]

    public init(
        documentID: UUID = UUID(),
        facts: [Fact]? = nil,
        pollsBeforeReady: Int = 1,
        terminalProcessingStatus: ProcessingStatus? = nil,
        failurePoint: MockFailurePoint? = nil,
        failuresRemaining: Int = 1,
        topics: [Topic] = [],
        visits: [Visit] = [],
        tasks: [Task] = []
    ) {
        self.documentID = documentID
        self.pollsBeforeReady = max(0, pollsBeforeReady)
        self.terminalProcessingStatus = terminalProcessingStatus
        self.failurePoint = failurePoint
        self.failuresRemaining = max(0, failuresRemaining)
        self.topics = topics
        self.visits = visits
        self.tasks = tasks
        self.facts = facts ?? [
            Fact(
                documentID: documentID,
                value: "Synthetic imported fact",
                sourceReference: SourceReference(documentID: documentID, locator: "page:1"),
                state: .needsReview
            )
        ]
    }
}

/// Deterministic, in-memory substitute for the future generated API client.
public actor DeterministicMockAPIClient: PatientAPIClient {
    private let scenario: MockImportScenario
    private var remainingFailures: Int
    private var processingPolls = 0
    private var storedFacts: [UUID: Fact]
    private var storedTopics: [UUID: Topic]
    private var storedVisits: [UUID: Visit]
    private var storedTasks: [UUID: Task]
    private var storedUploadSessions: [UUID: UploadSession] = [:]
    private var storedDocuments: [UUID: Document] = [:]
    private var storedShares: [UUID: ShareVersion] = [:]

    public init(scenario: MockImportScenario = MockImportScenario()) {
        self.scenario = scenario
        self.remainingFailures = scenario.failuresRemaining
        self.storedFacts = Dictionary(uniqueKeysWithValues: scenario.facts.map { ($0.id, $0) })
        self.storedTopics = Dictionary(uniqueKeysWithValues: scenario.topics.map { ($0.id, $0) })
        self.storedVisits = Dictionary(uniqueKeysWithValues: scenario.visits.map { ($0.id, $0) })
        self.storedTasks = Dictionary(uniqueKeysWithValues: scenario.tasks.map { ($0.id, $0) })
    }

    public func createImport(_ request: ImportRequest) async throws -> ImportTicket {
        try failIfNeeded(at: .createImport)
        let document = Document(id: scenario.documentID, title: request.fileName, processingStatus: .uploaded)
        storedDocuments[document.id] = document
        return ImportTicket(documentID: scenario.documentID, title: request.title)
    }

    public func upload(_ request: UploadRequest) async throws -> UploadReceipt {
        try failIfNeeded(at: .upload)
        return UploadReceipt(ticketID: request.ticketID, documentID: scenario.documentID)
    }

    public func createUploadSession(documentID: UUID, idempotencyKey: String?) async throws -> UploadSession {
        try failIfNeeded(at: .createUploadSession)
        let session = UploadSession(
            documentID: documentID,
            sizeBytes: 1,
            sha256: String(repeating: "0", count: 64),
            mediaType: "application/octet-stream",
            expiresAt: Date().addingTimeInterval(900)
        )
        storedUploadSessions[session.id] = session
        return session
    }

    public func uploadSessionContent(sessionID: UUID, content: Data) async throws -> UploadSession {
        try failIfNeeded(at: .uploadSessionContent)
        guard var session = storedUploadSessions[sessionID], !content.isEmpty else {
            throw PatientAPIClientError.notFound
        }
        session.status = .verified
        session.verifiedAt = Date()
        storedUploadSessions[sessionID] = session
        return session
    }

    public func listDocuments() async throws -> [Document] {
        try failIfNeeded(at: .listDocuments)
        return storedDocuments.values.sorted { $0.updatedAt > $1.updatedAt }
    }

    public func processingStatus(documentID: UUID) async throws -> ProcessingStatus {
        try failIfNeeded(at: .processingStatus)
        if let terminalProcessingStatus = scenario.terminalProcessingStatus {
            return terminalProcessingStatus
        }
        processingPolls += 1
        let status: ProcessingStatus = processingPolls > scenario.pollsBeforeReady ? .ready : .processing
        if status == .ready, var document = storedDocuments[documentID] {
            document.processingStatus = .ready
            document.updatedAt = Date()
            storedDocuments[documentID] = document
        }
        return status
    }

    public func facts(documentID: UUID) async throws -> [Fact] {
        try failIfNeeded(at: .facts)
        return storedFacts.values.sorted { $0.id.uuidString < $1.id.uuidString }
    }

    public func editFact(_ command: FactEditCommand) async throws -> Fact {
        try failIfNeeded(at: .editFact)
        guard var fact = storedFacts[command.factID], fact.documentID == command.documentID else {
            throw PatientAppError.factNotFound
        }
        fact.value = command.value
        storedFacts[fact.id] = fact
        return fact
    }

    public func confirmFact(_ command: FactReviewCommand) async throws -> Fact {
        try failIfNeeded(at: .confirmFact)
        guard var fact = storedFacts[command.factID], fact.documentID == command.documentID else {
            throw PatientAppError.factNotFound
        }
        guard command.ifMatchVersion == fact.version else {
            throw PatientAppError.versionConflict
        }
        try fact.confirmAfterExplicitReview()
        storedFacts[fact.id] = fact
        return fact
    }

    public func createTopic(_ request: TopicCreateRequest) async throws -> Topic {
        let topic = Topic(name: request.name)
        storedTopics[topic.id] = topic
        return topic
    }

    public func createVisit(_ request: VisitCreateRequest) async throws -> Visit {
        let visit = Visit(title: request.title, scheduledAt: request.startsAt, topicIDs: request.topicIDs)
        storedVisits[visit.id] = visit
        return visit
    }

    public func createTask(_ request: TaskCreateRequest) async throws -> Task {
        let task = Task(title: request.title, visitID: request.visitID, dueAt: request.dueAt)
        storedTasks[task.id] = task
        return task
    }

    public func listTopics() async throws -> [Topic] {
        try failIfNeeded(at: .listTopics)
        return storedTopics.values.sorted { $0.id.uuidString < $1.id.uuidString }
    }

    public func listVisits() async throws -> [Visit] {
        try failIfNeeded(at: .listVisits)
        return storedVisits.values.sorted { $0.id.uuidString < $1.id.uuidString }
    }

    public func listTasks() async throws -> [Task] {
        try failIfNeeded(at: .listTasks)
        return storedTasks.values.sorted { $0.id.uuidString < $1.id.uuidString }
    }

    public func createShare(_ request: ShareCreateRequest) async throws -> ShareCreation {
        try failIfNeeded(at: .createShare)
        let share = ShareVersion(
            documentID: request.resourceID,
            version: request.resourceVersion,
            resourceType: request.resourceType,
            resourceID: request.resourceID,
            expiresAt: request.expiresAt
        )
        storedShares[share.id] = share
        let token = ["synthetic", "share", share.id.uuidString].joined(separator: "-")
        return ShareCreation(share: share, token: token)
    }

    public func revokeShare(id: UUID) async throws -> ShareVersion {
        try failIfNeeded(at: .revokeShare)
        guard var share = storedShares[id] else { throw PatientAPIClientError.notFound }
        try share.revoke()
        storedShares[id] = share
        return share
    }

    public func shareStatus(id: UUID) async throws -> ShareAccessStatus {
        try failIfNeeded(at: .shareStatus)
        guard let share = storedShares[id] else { throw PatientAPIClientError.notFound }
        if share.state == .revoked {
            return ShareAccessStatus(share: share, state: .revoked)
        }
        if let expiresAt = share.expiresAt, expiresAt <= Date() {
            return ShareAccessStatus(share: share, state: .expired)
        }
        return ShareAccessStatus(share: share, state: .active)
    }

    public func exportPDF(documentID: UUID, documentVersion: Int) async throws -> PDFExportArtifact {
        try failIfNeeded(at: .exportPDF)
        guard documentVersion > 0 else { throw PatientAPIClientError.invalidRequest }
        let data = Data("%PDF-1.4\nsynthetic export\n".utf8)
        return PDFExportArtifact(
            data: data,
            contentType: "application/pdf",
            documentVersion: documentVersion,
            sha256: String(repeating: "a", count: 64)
        )
    }

    private func failIfNeeded(at point: MockFailurePoint) throws {
        guard scenario.failurePoint == point, remainingFailures > 0 else { return }
        remainingFailures -= 1
        switch point {
        case .processingStatus: throw PatientAppError.processingFailed
        case .upload: throw PatientAppError.uploadFailed
        default: throw PatientAppError.unavailable
        }
    }
}
