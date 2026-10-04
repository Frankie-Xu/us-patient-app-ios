import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class VisitPreparationModelTests: XCTestCase {
    func testVisitCreationTransitionsFromEmptyToSaved() async {
        let model = VisitPreparationModel(client: DeterministicMockAPIClient())
        XCTAssertEqual(model.visitState, .empty)
        await model.createVisit(VisitCreateRequest(title: "Primary care"))
        guard case let .saved(visits) = model.visitState else { return XCTFail("Expected saved visit state") }
        XCTAssertEqual(visits.map(\.title), ["Primary care"])
    }

    func testTaskCreationCanReferenceCreatedVisit() async throws {
        let model = VisitPreparationModel(client: DeterministicMockAPIClient())
        await model.createVisit(VisitCreateRequest(title: "Follow-up"))
        let visit = try XCTUnwrap(model.visitState.items.first)
        await model.createTask(TaskCreateRequest(title: "Bring questions", visitID: visit.id))
        XCTAssertEqual(model.taskState.items.first?.visitID, visit.id)
    }

    func testInvalidTitleIsFailedAndNotRetryable() async {
        let model = VisitPreparationModel(client: DeterministicMockAPIClient())
        await model.createTask(TaskCreateRequest(title: "   "))
        XCTAssertEqual(model.taskState.failure, .invalidInput)
        XCTAssertFalse(model.taskState.failure?.canRetry ?? true)
    }

    func testTransientFailurePreservesRetryAndReusesStableRequest() async {
        let model = VisitPreparationModel(client: OneShotVisitFailureClient())
        await model.createVisit(VisitCreateRequest(title: "Retry me"))
        XCTAssertEqual(model.visitState.failure, .unavailable)
        await model.retryVisit()
        XCTAssertEqual(model.visitState.items.first?.title, "Retry me")
    }
}

private actor OneShotVisitFailureClient: PatientAPIClient {
    private var failed = false
    func createImport(_ request: ImportRequest) async throws -> ImportTicket { throw PatientAPIClientError.unsupported(.topicCreationNotInClient) }
    func upload(_ request: UploadRequest) async throws -> UploadReceipt { throw PatientAPIClientError.unsupported(.topicCreationNotInClient) }
    func processingStatus(documentID: UUID) async throws -> ProcessingStatus { .ready }
    func facts(documentID: UUID) async throws -> [Fact] { [] }
    func editFact(_ command: FactEditCommand) async throws -> Fact { throw PatientAppError.factNotFound }
    func confirmFact(_ command: FactReviewCommand) async throws -> Fact { throw PatientAppError.factNotFound }
    func createVisit(_ request: VisitCreateRequest) async throws -> Visit {
        if !failed { failed = true; throw PatientAPIClientError.transport }
        return Visit(title: request.title)
    }
    func createTask(_ request: TaskCreateRequest) async throws -> PatientAppDomain.Task { PatientAppDomain.Task(title: request.title) }
}
