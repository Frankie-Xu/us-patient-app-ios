import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class DocumentVersionHistoryModelTests: XCTestCase {
    func testLoadsVersionsSortedNewestFirst() async {
        let documentID = UUID()
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let versions = [
            DocumentVersion(documentID: documentID, title: "v1", state: .draft, processingStatus: .ready, version: 1, createdAt: now, updatedAt: now),
            DocumentVersion(documentID: documentID, title: "v3", state: .needsReview, processingStatus: .ready, version: 3, createdAt: now, updatedAt: now.addingTimeInterval(2)),
            DocumentVersion(documentID: documentID, title: "v2", state: .needsReview, processingStatus: .processing, version: 2, createdAt: now, updatedAt: now.addingTimeInterval(1))
        ]
        let model = DocumentVersionHistoryModel { requestedID in
            XCTAssertEqual(requestedID, documentID)
            return versions
        }

        await model.load(documentID: documentID)

        guard case let .loaded(loaded) = model.state else {
            return XCTFail("Expected versions to load")
        }
        XCTAssertEqual(loaded.map(\.version), [3, 2, 1])
        XCTAssertEqual(loaded.first?.title, "v3")
    }

    func testFailureCanBeRetriedThroughInjectedLoader() async {
        let documentID = UUID()
        let version = DocumentVersion(
            documentID: documentID,
            title: "Recovered",
            state: .needsReview,
            processingStatus: .ready,
            version: 2,
            createdAt: .now,
            updatedAt: .now
        )
        let loader = OneShotVersionLoader(result: [version])
        let model = DocumentVersionHistoryModel { requestedID in
            try await loader.load(documentID: requestedID)
        }

        await model.load(documentID: documentID)
        XCTAssertEqual(model.state, .failed(.transport))

        await model.retry()

        XCTAssertEqual(model.state, .loaded([version]))
    }
}

private actor OneShotVersionLoader {
    private var shouldFail = true
    private let result: [DocumentVersion]

    init(result: [DocumentVersion]) {
        self.result = result
    }

    func load(documentID: UUID) throws -> [DocumentVersion] {
        if shouldFail {
            shouldFail = false
            throw PatientAPIClientError.transport
        }
        return result.filter { $0.documentID == documentID }
    }
}
