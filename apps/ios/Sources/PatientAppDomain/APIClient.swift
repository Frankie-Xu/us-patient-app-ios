import Foundation

/// The replaceable boundary for the future generated OpenAPI client.
/// This protocol intentionally contains no URL, authentication, or vendor payload details.
/// TODO(API #8): map these local commands and results to the generated contract once it lands.
public protocol PatientAPIClient: Sendable {
    func createImport(_ request: ImportRequest) async throws -> ImportTicket
    func upload(_ request: UploadRequest) async throws -> UploadReceipt
    func processingStatus(documentID: UUID) async throws -> ProcessingStatus
    func facts(documentID: UUID) async throws -> [Fact]
    func editFact(_ command: FactEditCommand) async throws -> Fact
    func confirmFact(_ command: FactReviewCommand) async throws -> Fact
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
