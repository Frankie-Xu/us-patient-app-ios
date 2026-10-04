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
}
