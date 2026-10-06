import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class DocumentDetailModelTests: XCTestCase {
    func testDetailBuildsSourceLocationsAndNewestVersionFirst() async {
        let documentID = UUID()
        let document = Document(id: documentID, title: "visit.pdf", processingStatus: .ready, version: 3)
        let fact = Fact(
            documentID: documentID,
            value: "Hemoglobin",
            sourceReference: SourceReference(documentID: documentID, locator: "page:4"),
            state: .needsReview
        )
        let versions = [
            DocumentVersion(documentID: documentID, title: "v1", state: .draft, processingStatus: .ready, version: 1, createdAt: .now, updatedAt: .now),
            DocumentVersion(documentID: documentID, title: "v3", state: .needsReview, processingStatus: .ready, version: 3, createdAt: .now, updatedAt: .now)
        ]
        let model = DocumentDetailModel { requestedID in
            XCTAssertEqual(requestedID, documentID)
            return DocumentDetailPresentation(document: document, facts: [fact], versions: versions)
        }

        await model.load(documentID: documentID)

        guard case let .loaded(detail) = model.state else {
            return XCTFail("Expected detail to load")
        }
        XCTAssertEqual(detail.document.id, documentID)
        XCTAssertEqual(detail.versions.map(\.version), [3, 1])
        XCTAssertEqual(detail.sourceLocations.first?.pageNumber, 4)
        XCTAssertEqual(detail.sourceLocations.first?.displayLabel, "Page 4 · page:4")
    }

    func testEmptyFactsUseAnExplicitEmptyState() async {
        let document = Document(title: "empty.pdf", processingStatus: .ready)
        let model = DocumentDetailModel { _ in
            DocumentDetailPresentation(document: document, facts: [])
        }

        await model.load(documentID: document.id)

        XCTAssertEqual(model.state, .empty)
    }
}
