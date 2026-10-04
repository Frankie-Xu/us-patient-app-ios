import Foundation

/// Session gate used by the app shell before handing requests to a transport.
/// It observes AuthSession state only; it never handles JWTs or stores tokens.
public struct AuthenticatedPatientAPIClient: PatientAPIClient, Sendable {
    private let client: any PatientAPIClient
    private let authSession: any AuthSession

    public init(client: any PatientAPIClient, authSession: any AuthSession) {
        self.client = client
        self.authSession = authSession
    }

    public func createImport(_ request: ImportRequest) async throws -> ImportTicket { try await withAuthorization { try await client.createImport(request) } }
    public func upload(_ request: UploadRequest) async throws -> UploadReceipt { try await withAuthorization { try await client.upload(request) } }
    public func processingStatus(documentID: UUID) async throws -> ProcessingStatus { try await withAuthorization { try await client.processingStatus(documentID: documentID) } }
    public func facts(documentID: UUID) async throws -> [Fact] { try await withAuthorization { try await client.facts(documentID: documentID) } }
    public func editFact(_ command: FactEditCommand) async throws -> Fact { try await withAuthorization { try await client.editFact(command) } }
    public func confirmFact(_ command: FactReviewCommand) async throws -> Fact { try await withAuthorization { try await client.confirmFact(command) } }
    public func createTopic(_ request: TopicCreateRequest) async throws -> Topic { try await withAuthorization { try await client.createTopic(request) } }
    public func createVisit(_ request: VisitCreateRequest) async throws -> Visit { try await withAuthorization { try await client.createVisit(request) } }
    public func createTask(_ request: TaskCreateRequest) async throws -> Task { try await withAuthorization { try await client.createTask(request) } }
    public func listTopics() async throws -> [Topic] { try await withAuthorization { try await client.listTopics() } }
    public func listVisits() async throws -> [Visit] { try await withAuthorization { try await client.listVisits() } }
    public func listTasks() async throws -> [Task] { try await withAuthorization { try await client.listTasks() } }
    public func createShare(_ request: ShareCreateRequest) async throws -> ShareCreation { try await withAuthorization { try await client.createShare(request) } }
    public func revokeShare(id: UUID) async throws -> ShareVersion { try await withAuthorization { try await client.revokeShare(id: id) } }

    private func withAuthorization<T: Sendable>(_ operation: () async throws -> T) async throws -> T {
        guard case let .signedIn(initialSession) = await authSession.authState() else {
            throw PatientAPIClientError.unauthorized
        }
        let result = try await operation()
        // A request may outlive logout or account switching. Do not surface a
        // response that was completed under a stale authorization epoch.
        guard case let .signedIn(currentSession) = await authSession.authState(), currentSession == initialSession else {
            throw PatientAPIClientError.unauthorized
        }
        return result
    }
}
