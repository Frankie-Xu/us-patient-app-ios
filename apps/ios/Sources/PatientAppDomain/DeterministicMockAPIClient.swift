import Foundation

public enum MockFailurePoint: Equatable, Sendable {
    case createImport
    case upload
    case processingStatus
    case facts
    case editFact
    case confirmFact
}

public struct MockImportScenario: Sendable {
    public let documentID: UUID
    public let facts: [Fact]
    public let pollsBeforeReady: Int
    public let failurePoint: MockFailurePoint?
    public let failuresRemaining: Int

    public init(
        documentID: UUID = UUID(),
        facts: [Fact]? = nil,
        pollsBeforeReady: Int = 1,
        failurePoint: MockFailurePoint? = nil,
        failuresRemaining: Int = 1
    ) {
        self.documentID = documentID
        self.pollsBeforeReady = max(0, pollsBeforeReady)
        self.failurePoint = failurePoint
        self.failuresRemaining = max(0, failuresRemaining)
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

    public init(scenario: MockImportScenario = MockImportScenario()) {
        self.scenario = scenario
        self.remainingFailures = scenario.failuresRemaining
        self.storedFacts = Dictionary(uniqueKeysWithValues: scenario.facts.map { ($0.id, $0) })
    }

    public func createImport(_ request: ImportRequest) async throws -> ImportTicket {
        try failIfNeeded(at: .createImport)
        return ImportTicket(documentID: scenario.documentID, title: request.title)
    }

    public func upload(_ request: UploadRequest) async throws -> UploadReceipt {
        try failIfNeeded(at: .upload)
        return UploadReceipt(ticketID: request.ticketID, documentID: scenario.documentID)
    }

    public func processingStatus(documentID: UUID) async throws -> ProcessingStatus {
        try failIfNeeded(at: .processingStatus)
        processingPolls += 1
        return processingPolls > scenario.pollsBeforeReady ? .ready : .processing
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
