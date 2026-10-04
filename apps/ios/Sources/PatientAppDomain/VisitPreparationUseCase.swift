import Foundation

/// Creates patient-entered planning items without deriving clinical instructions.
public struct VisitPreparationUseCase: Sendable {
    private let client: any PatientAPIClient

    public init(client: any PatientAPIClient) { self.client = client }

    public func createVisit(_ request: VisitCreateRequest) async throws -> Visit {
        let title = try validatedTitle(request.title)
        return try await client.createVisit(VisitCreateRequest(title: title, startsAt: request.startsAt, topicIDs: request.topicIDs, idempotencyKey: request.idempotencyKey))
    }

    public func createTask(_ request: TaskCreateRequest) async throws -> Task {
        let title = try validatedTitle(request.title)
        return try await client.createTask(TaskCreateRequest(title: title, visitID: request.visitID, dueAt: request.dueAt, idempotencyKey: request.idempotencyKey))
    }

    private func validatedTitle(_ value: String) throws -> String {
        let title = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { throw PatientAppError.invalidInput }
        return title
    }
}
