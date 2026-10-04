import XCTest
@testable import PatientAppDomain

final class ImportTests: XCTestCase {
    func testImportUseCaseExposesUploadProcessingAndFactsStages() async throws {
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(pollsBeforeReady: 2))
        let useCase = ImportUseCase(client: client)
        let recorder = StageRecorder()

        let snapshot = try await useCase.run(ImportRequest(fileName: "synthetic.txt", title: "Synthetic")) { stage in
            await recorder.append(stage)
        }

        let stages = await recorder.values
        XCTAssertEqual(stages, [.uploading, .processing, .loadingFacts])
        XCTAssertEqual(snapshot.status, .ready)
        XCTAssertEqual(snapshot.facts.count, 1)
        XCTAssertTrue(snapshot.facts[0].isTraceable)
        XCTAssertEqual(snapshot.facts[0].state, .needsReview)
    }

    func testTransientUploadFailureCanBeRetriedWithSameMock() async throws {
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(failurePoint: .upload))
        let useCase = ImportUseCase(client: client)
        let request = ImportRequest(fileName: "synthetic.txt", title: "Synthetic")

        do {
            _ = try await useCase.run(request)
            XCTFail("The first upload should fail")
        } catch let error as PatientAppError {
            XCTAssertEqual(error, .uploadFailed)
        }

        let snapshot = try await useCase.run(request)
        XCTAssertEqual(snapshot.status, .ready)
    }

    func testEmptyFactsRemainAnExplicitEmptyResult() async throws {
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(facts: []))
        let snapshot = try await ImportUseCase(client: client).run(ImportRequest(fileName: "empty.txt", title: "Empty"))
        XCTAssertTrue(snapshot.facts.isEmpty)
    }

    func testEditThenConfirmRequiresTheEditedFactToBeReviewed() async throws {
        let client = DeterministicMockAPIClient()
        let useCase = ImportUseCase(client: client)
        let snapshot = try await useCase.run(ImportRequest(fileName: "synthetic.txt", title: "Synthetic"))
        let original = try XCTUnwrap(snapshot.facts.first)

        let edited = try await useCase.editFact(FactEditCommand(documentID: snapshot.ticket.documentID, factID: original.id, value: "Edited synthetic fact"))
        XCTAssertEqual(edited.state, .needsReview)
        XCTAssertEqual(edited.value, "Edited synthetic fact")

        let confirmed = try await useCase.confirmFact(FactReviewCommand(documentID: snapshot.ticket.documentID, factID: edited.id))
        XCTAssertTrue(confirmed.canAppearInDoctorView)
    }
}

private actor StageRecorder {
    private var recorded: [ImportStage] = []

    func append(_ stage: ImportStage) {
        recorded.append(stage)
    }

    var values: [ImportStage] { recorded }
    func testLoadingExistingDocumentUsesFactsWithoutUpload() async throws {
        let documentID = UUID()
        let fact = Fact(
            documentID: documentID,
            value: "Historical fact",
            sourceReference: SourceReference(documentID: documentID, locator: "page:2"),
            state: .needsReview
        )
        let client = DeterministicMockAPIClient(
            scenario: MockImportScenario(documentID: documentID, facts: [fact], pollsBeforeReady: 0)
        )
        let document = Document(id: documentID, title: "history.pdf", processingStatus: .ready)

        let snapshot = try await ImportUseCase(client: client).loadExisting(document)

        XCTAssertEqual(snapshot.ticket.title, "history.pdf")
        XCTAssertEqual(snapshot.status, .ready)
        XCTAssertEqual(snapshot.facts, [fact])
    }

}
