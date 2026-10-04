import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class AccountHistoryModelTests: XCTestCase {
    func testModelReportsLoadedHistory() async {
        let visit = Visit(title: "Follow-up")
        let model = AccountHistoryModel(client: DeterministicMockAPIClient(scenario: MockImportScenario(visits: [visit])))
        await model.load()

        guard case let .loaded(snapshot) = model.state else { return XCTFail("Expected loaded history") }
        XCTAssertEqual(snapshot.visits, [visit])
    }

    func testModelReportsExplicitEmptyState() async {
        let model = AccountHistoryModel(client: DeterministicMockAPIClient(scenario: MockImportScenario()))
        await model.load()
        XCTAssertEqual(model.state, .empty)
    }

    func testModelPreservesTypedFailureAndRetries() async {
        let model = AccountHistoryModel(client: OneShotHistoryFailureClient())
        await model.load()
        XCTAssertEqual(model.state, .failed(.transport))

        await model.retry()
        guard case let .loaded(snapshot) = model.state else { return XCTFail("Expected retry to load history") }
        XCTAssertEqual(snapshot.tasks.first?.title, "Retry task")
    }
}

private actor OneShotHistoryFailureClient: PatientAPIClient {
    private var failed = false

    func createImport(_ request: ImportRequest) async throws -> ImportTicket { throw PatientAPIClientError.unsupported(.topicCreationNotInClient) }
    func upload(_ request: UploadRequest) async throws -> UploadReceipt { throw PatientAPIClientError.unsupported(.topicCreationNotInClient) }
    func processingStatus(documentID: UUID) async throws -> ProcessingStatus { .ready }
    func facts(documentID: UUID) async throws -> [Fact] { [] }
    func editFact(_ command: FactEditCommand) async throws -> Fact { throw PatientAppError.factNotFound }
    func confirmFact(_ command: FactReviewCommand) async throws -> Fact { throw PatientAppError.factNotFound }
    func createVisit(_ request: VisitCreateRequest) async throws -> Visit { Visit(title: request.title) }
    func createTask(_ request: TaskCreateRequest) async throws -> Task {
        return Task(title: request.title)
    }
    func listTopics() async throws -> [Topic] { [] }
    func listVisits() async throws -> [Visit] { [] }
    func listTasks() async throws -> [Task] {
        if !failed { failed = true; throw PatientAPIClientError.transport }
        return [Task(title: "Retry task")]
    }
}
