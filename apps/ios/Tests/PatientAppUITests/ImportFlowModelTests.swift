import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class ImportFlowModelTests: XCTestCase {
    func testModelTransitionsToReviewAndThenCompleted() async throws {
        let model = ImportFlowModel(client: DeterministicMockAPIClient())
        await model.start(ImportRequest(fileName: "synthetic.txt", title: "Synthetic"))

        guard case let .reviewRequired(snapshot) = model.state else {
            return XCTFail("Expected review-required state")
        }
        let fact = try XCTUnwrap(snapshot.facts.first)
        await model.editFact(fact, value: "Edited synthetic fact")
        guard case let .reviewRequired(editedSnapshot) = model.state else {
            return XCTFail("Editing must keep the fact in review-required state")
        }
        let edited = try XCTUnwrap(editedSnapshot.facts.first)
        await model.confirmFact(edited)
        guard case .completed = model.state else {
            return XCTFail("Expected completed state after explicit confirmation")
        }
    }

    func testModelExposesFailureAndRetry() async {
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(failurePoint: .upload))
        let model = ImportFlowModel(client: client)
        let request = ImportRequest(fileName: "synthetic.txt", title: "Synthetic")

        await model.start(request)
        XCTAssertEqual(model.error, .uploadFailed)
        await model.retry()
        if case .reviewRequired = model.state {
            // Expected: the deterministic one-shot failure is recovered by retry.
        } else {
            XCTFail("Expected review-required state after retry")
        }
    }

    func testModelExposesEmptyState() async {
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(facts: []))
        let model = ImportFlowModel(client: client)
        await model.start(ImportRequest(fileName: "empty.txt", title: "Empty"))
        if case .empty = model.state {
            // Expected.
        } else {
            XCTFail("Expected explicit empty state")
        }
    }
}
