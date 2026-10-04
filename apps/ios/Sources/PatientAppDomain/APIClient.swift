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

    public init(client: any PatientAPIClient) {
        self.client = client
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

        var status = try await client.processingStatus(documentID: ticket.documentID)
        while status == .queued || status == .processing {
            status = try await client.processingStatus(documentID: ticket.documentID)
        }
        guard status == .ready else { throw PatientAppError.processingFailed }

        await onStage(.loadingFacts)
        let facts = try await client.facts(documentID: ticket.documentID)
        return ImportSnapshot(ticket: ticket, receipt: receipt, status: status, facts: facts)
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
