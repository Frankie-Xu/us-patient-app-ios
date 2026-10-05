import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class ImportFlowModelTests: XCTestCase {
    func testHistoricalFactConfirmationUsesDisplayedVersion() async throws {
        let documentID = UUID()
        let fact = Fact(documentID: documentID, value: "Synthetic v7 fact", sourceReference: SourceReference(documentID: documentID, locator: "page:2"), state: .needsReview, version: 7)
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(documentID: documentID, facts: [fact], pollsBeforeReady: 0))
        let model = ImportFlowModel(client: client)
        await model.loadExisting(document: Document(id: documentID, title: "synthetic-v7.txt", processingStatus: .ready, version: 7))
        await model.confirmFact(fact)
        XCTAssertTrue(model.canPrepareVisit)
        XCTAssertEqual(model.currentSnapshot?.facts.first?.state, .confirmed)
    }

    func testReviewFailurePreservesSnapshotForRetry() async throws {
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(pollsBeforeReady: 0, failurePoint: .confirmFact))
        let model = ImportFlowModel(client: client)
        await model.start(ImportRequest(fileName: "synthetic.txt", title: "Synthetic"))
        let snapshot = try XCTUnwrap(model.currentSnapshot)
        await model.confirmFact(try XCTUnwrap(snapshot.facts.first))
        XCTAssertEqual(model.currentSnapshot, snapshot)
        XCTAssertFalse(model.canPrepareVisit)
        await model.retry()
        let recovered = try XCTUnwrap(model.currentSnapshot)
        await model.confirmFact(try XCTUnwrap(recovered.facts.first))
        XCTAssertTrue(model.canPrepareVisit)
    }

    func testCurrentImportTitleUsesTheSelectedRecordTitle() async {
        let model = ImportFlowModel(
            client: DeterministicMockAPIClient(
                scenario: MockImportScenario(pollsBeforeReady: 0)
            )
        )

        await model.start(ImportRequest(fileName: "visit.pdf", title: "Visit summary"))

        XCTAssertEqual(model.currentImportTitle, "Visit summary")
        XCTAssertTrue(model.state != .idle)
    }
    func testLoadingExistingDocumentMakesFactsReviewable() async {
        let documentID = UUID()
        let fact = Fact(
            documentID: documentID,
            value: "Historical fact",
            sourceReference: SourceReference(documentID: documentID, locator: "page:1"),
            state: .needsReview
        )
        let client = DeterministicMockAPIClient(
            scenario: MockImportScenario(documentID: documentID, facts: [fact], pollsBeforeReady: 0)
        )
        let model = ImportFlowModel(client: client)

        await model.loadExisting(document: Document(id: documentID, title: "history.pdf", processingStatus: .ready))

        guard case let .reviewRequired(snapshot) = model.state else {
            return XCTFail("Expected historical facts to be reviewable")
        }
        XCTAssertEqual(snapshot.ticket.title, "history.pdf")
        XCTAssertEqual(snapshot.facts, [fact])
    }

}
