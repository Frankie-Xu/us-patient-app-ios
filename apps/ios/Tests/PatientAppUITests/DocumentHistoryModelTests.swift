import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class DocumentHistoryModelTests: XCTestCase {
    func testLoadReturnsSortedDocumentHistory() async throws {
        let client = DeterministicMockAPIClient()
        _ = try await client.createImport(ImportRequest(fileName: "older.txt", title: "Older"))
        let model = DocumentHistoryModel(client: client)

        await model.load()

        let documents = try XCTUnwrap(model.state.documents)
        XCTAssertEqual(documents.count, 1)
        XCTAssertEqual(documents.first?.title, "older.txt")
        XCTAssertEqual(documents.first?.processingStatus, .uploaded)
    }

    func testLoadSurfacesTransportFailureAndRetryCanRecover() async throws {
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(failurePoint: .listDocuments))
        let model = DocumentHistoryModel(client: client)

        await model.load()

        XCTAssertEqual(model.state, .failed(.transport))
        await model.retry()
        XCTAssertEqual(model.state, .empty)
    }
}
