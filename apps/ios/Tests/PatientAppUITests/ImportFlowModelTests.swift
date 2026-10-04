import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class ImportFlowModelTests: XCTestCase {
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
