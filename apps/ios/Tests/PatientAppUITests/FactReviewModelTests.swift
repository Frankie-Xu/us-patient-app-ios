import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class FactReviewModelTests: XCTestCase {
    func testConflictCannotBeConfirmedUntilResolved() throws {
        let documentID = UUID()
        let fact = Fact(
            documentID: documentID,
            value: "Conflicting",
            sourceReference: SourceReference(documentID: documentID, locator: "page:1"),
            state: .needsReview,
            confidence: 0.99
        )
        let model = FactReviewModel(facts: [fact], conflictFactIDs: [fact.id])

        XCTAssertFalse(model.presentations[0].canConfirm)
        XCTAssertEqual(model.presentations[0].actionState, .blocked([.conflict]))
        XCTAssertThrowsError(try model.applyExplicitConfirmation(to: fact))

        model.markConflict(for: fact.id, conflicted: false)
        let confirmed = try model.applyExplicitConfirmation(to: fact)
        XCTAssertEqual(confirmed.state, .confirmed)
        XCTAssertTrue(confirmed.wasExplicitlyReviewed)
    }

    func testLowConfidencePresentationIsNeverAutomaticallyConfirmable() {
        let fact = Fact(
            documentID: UUID(),
            value: "Uncertain",
            sourceReference: SourceReference(documentID: UUID(), locator: "page:1"),
            state: .needsReview,
            confidence: 0.2
        )
        let model = FactReviewModel(facts: [fact])

        XCTAssertFalse(model.presentations[0].canConfirm)
        XCTAssertFalse(model.presentations[0].isAutomaticallyConfirmable)
        XCTAssertEqual(model.presentations[0].blockers, [.lowConfidence(0.2), .missingSource])
    }
}
