import Foundation

/// The replaceable boundary for the future generated OpenAPI client.
/// This protocol intentionally contains no URL, authentication, or vendor payload details.
/// TODO(API #8): map these local commands and results to the generated contract once it lands.
public protocol PatientAPIClient: Sendable {
    func createImport(_ request: ImportRequest) async throws -> ImportTicket
    func upload(_ request: UploadRequest) async throws -> UploadReceipt
    func createUploadSession(documentID: UUID, idempotencyKey: String?) async throws -> UploadSession
    func uploadSessionContent(sessionID: UUID, content: Data) async throws -> UploadSession
    func processingStatus(documentID: UUID) async throws -> ProcessingStatus
    func facts(documentID: UUID) async throws -> [Fact]
    func editFact(_ command: FactEditCommand) async throws -> Fact
    func confirmFact(_ command: FactReviewCommand) async throws -> Fact
    func createTopic(_ request: TopicCreateRequest) async throws -> Topic
    func createVisit(_ request: VisitCreateRequest) async throws -> Visit
    func createTask(_ request: TaskCreateRequest) async throws -> Task
    func listTopics() async throws -> [Topic]
    func listVisits() async throws -> [Visit]
    func listTasks() async throws -> [Task]
    func createShare(_ request: ShareCreateRequest) async throws -> ShareCreation
    func revokeShare(id: UUID) async throws -> ShareVersion
}

public struct TopicCreateRequest: Codable, Equatable, Hashable, Sendable {
    public let name: String

    public init(name: String) { self.name = name }
}

public struct VisitCreateRequest: Codable, Equatable, Hashable, Sendable {
    public let title: String
    public let startsAt: Date?
    public let topicIDs: [UUID]
    public let idempotencyKey: String?

    public init(title: String, startsAt: Date? = nil, topicIDs: [UUID] = [], idempotencyKey: String? = nil) {
        self.title = title
        self.startsAt = startsAt
        self.topicIDs = topicIDs
        self.idempotencyKey = idempotencyKey
    }
}

public struct TaskCreateRequest: Codable, Equatable, Hashable, Sendable {
    public let title: String
    public let visitID: UUID?
    public let dueAt: Date?
    public let idempotencyKey: String?

    public init(title: String, visitID: UUID? = nil, dueAt: Date? = nil, idempotencyKey: String? = nil) {
        self.title = title
        self.visitID = visitID
        self.dueAt = dueAt
        self.idempotencyKey = idempotencyKey
    }
}

public struct ShareCreateRequest: Codable, Equatable, Hashable, Sendable {
    public let resourceType: SharedResourceType
    public let resourceID: UUID
    public let resourceVersion: Int
    public let expiresAt: Date
    public let idempotencyKey: String?

    public init(resourceType: SharedResourceType, resourceID: UUID, resourceVersion: Int, expiresAt: Date, idempotencyKey: String? = nil) {
        self.resourceType = resourceType
        self.resourceID = resourceID
        self.resourceVersion = resourceVersion
        self.expiresAt = expiresAt
        self.idempotencyKey = idempotencyKey
    }
}

public struct ShareCreation: Codable, Equatable, Hashable, Sendable {
    public let share: ShareVersion
    /// The raw access token is returned only for immediate handoff to the
    /// recipient. It is never persisted by this package.
    public let token: String

    public init(share: ShareVersion, token: String) {
        self.share = share
        self.token = token
    }
}

public struct VisitPack: Equatable, Sendable {
    public let visit: Visit
    public let topics: [Topic]
    public let tasks: [Task]

    public init(visit: Visit, topics: [Topic] = [], tasks: [Task] = []) {
        self.visit = visit
        self.topics = topics
        self.tasks = tasks
    }
}

public extension PatientAPIClient {
    /// Assembles a visit pack from the frozen typed visit/history endpoints;
    /// generation of a dedicated server pack endpoint remains replaceable.
    func visitPack(visitID: UUID) async throws -> VisitPack {
        async let visits = listVisits()
        async let topics = listTopics()
        async let tasks = listTasks()
        guard let visit = try await visits.first(where: { $0.id == visitID }) else {
            throw PatientAPIClientError.notFound
        }
        let allTopics = try await topics
        let allTasks = try await tasks
        return VisitPack(visit: visit, topics: allTopics.filter { visit.topicIDs.contains($0.id) }, tasks: allTasks.filter { $0.visitID == visitID })
    }
}

public extension PatientAPIClient {
    func createTopic(_ request: TopicCreateRequest) async throws -> Topic {
        throw PatientAPIClientError.unsupported(.topicCreationNotInClient)
    }

    func createVisit(_ request: VisitCreateRequest) async throws -> Visit {
        throw PatientAPIClientError.unsupported(.visitCreationNotInClient)
    }

    func createTask(_ request: TaskCreateRequest) async throws -> Task {
        throw PatientAPIClientError.unsupported(.taskCreationNotInClient)
    }

    func listTopics() async throws -> [Topic] {
        throw PatientAPIClientError.unsupported(.topicListingNotInClient)
    }

    func listVisits() async throws -> [Visit] {
        throw PatientAPIClientError.unsupported(.visitListingNotInClient)
    }

    func listTasks() async throws -> [Task] {
        throw PatientAPIClientError.unsupported(.taskListingNotInClient)
    }

    func createShare(_ request: ShareCreateRequest) async throws -> ShareCreation {
        throw PatientAPIClientError.unsupported(.shareCreationNotInClient)
    }

    func revokeShare(id: UUID) async throws -> ShareVersion {
        throw PatientAPIClientError.unsupported(.shareRevocationNotInClient)
    }

    func createUploadSession(documentID: UUID, idempotencyKey: String?) async throws -> UploadSession {
        throw PatientAPIClientError.unsupported(.uploadSessionCreationNotInClient)
    }

    func uploadSessionContent(sessionID: UUID, content: Data) async throws -> UploadSession {
        throw PatientAPIClientError.unsupported(.uploadContentNotInClient)
    }
}

public struct ImportUseCase: Sendable {
    private let client: any PatientAPIClient
    private let clock: any ImportClock
    private let retryPolicy: ImportRetryPolicy

    public init(client: any PatientAPIClient, clock: any ImportClock = SystemImportClock(), retryPolicy: ImportRetryPolicy = ImportRetryPolicy()) {
        self.client = client
        self.clock = clock
        self.retryPolicy = retryPolicy
    }

    public func run(
        _ request: ImportRequest,
        onStage: @escaping @Sendable (ImportStage) async -> Void = { _ in }
    ) async throws -> ImportSnapshot {
        guard !request.fileName.isEmpty, !request.title.isEmpty, request.byteCount > 0 else {
            throw PatientAppError.invalidInput
        }

        let ticket = try await client.createImport(request)
        await onStage(.uploading)
        if let content = request.content {
            guard content.count == request.byteCount, !content.isEmpty, content.count <= 10 * 1024 * 1024 else {
                throw PatientAppError.invalidInput
            }
            let session = try await client.createUploadSession(documentID: ticket.documentID, idempotencyKey: "\(ticket.documentID.uuidString)-upload")
            _ = try await client.uploadSessionContent(sessionID: session.id, content: content)
        }
        let receipt = try await client.upload(UploadRequest(ticketID: ticket.id, byteCount: request.byteCount))
        await onStage(.processing)

        let status = try await pollProcessing(documentID: ticket.documentID)

        await onStage(.loadingFacts)
        let facts = try await client.facts(documentID: ticket.documentID)
        return ImportSnapshot(ticket: ticket, receipt: receipt, status: status, facts: facts)
    }

    private func pollProcessing(documentID: UUID) async throws -> ProcessingStatus {
        let startedAt = clock.now
        var attempts = 0
        while true {
            try checkCancellation()
            guard clock.now.timeIntervalSince(startedAt) < durationSeconds(retryPolicy.maxDuration) else {
                throw PatientAppError.processingTimeout
            }

            let status: ProcessingStatus
            do {
                status = try await client.processingStatus(documentID: documentID)
            } catch is CancellationError {
                throw PatientAppError.processingCancelled
            }
            attempts += 1

            switch status {
            case .ready:
                return status
            case .failed:
                throw PatientAppError.processingFailed
            case .queued, .processing:
                guard attempts < retryPolicy.maxAttempts else { throw PatientAppError.processingTimeout }
                let delay = retryPolicy.delay(forRetry: attempts)
                guard clock.now.timeIntervalSince(startedAt) + durationSeconds(delay) <= durationSeconds(retryPolicy.maxDuration) else {
                    throw PatientAppError.processingTimeout
                }
                do {
                    try await clock.sleep(for: delay)
                } catch is CancellationError {
                    throw PatientAppError.processingCancelled
                }
            }
        }
    }

    private func checkCancellation() throws {
        if _Concurrency.Task.isCancelled { throw PatientAppError.processingCancelled }
    }

    private func durationSeconds(_ duration: Duration) -> TimeInterval {
        let components = duration.components
        return TimeInterval(components.seconds) + TimeInterval(components.attoseconds) / 1_000_000_000_000_000_000
    }

    public func editFact(_ command: FactEditCommand) async throws -> Fact {
        guard !command.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw PatientAppError.invalidInput
        }
        return try await client.editFact(command)
    }

    public func confirmFact(_ command: FactReviewCommand) async throws -> Fact {
        try await client.confirmFact(command)
    }
}
