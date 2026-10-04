import XCTest
@testable import PatientAppDomain

final class FactReviewPolicyTests: XCTestCase {
    func testLowConfidenceFactIsBlockedBeforeConfirmation() {
        let documentID = UUID()
        let fact = Fact(
            documentID: documentID,
            value: "Low confidence",
            sourceReference: SourceReference(documentID: documentID, locator: "page:1"),
            state: .needsReview,
            confidence: 0.42
        )

        XCTAssertEqual(
            FactReviewPolicy.actionState(for: fact),
            .blocked([.lowConfidence(0.42)])
        )
        XCTAssertThrowsError(try FactReviewPolicy.validateExplicitConfirmation(fact)) { error in
            XCTAssertEqual(error as? PatientAppError, .reviewRequired)
        }
    }

    func testMissingSourceAndConflictAreBothBlocking() {
        let fact = Fact(documentID: UUID(), value: "Untraceable", state: .needsReview)

        XCTAssertEqual(
            FactReviewPolicy.blockers(for: fact, conflictDetected: true),
            [.missingSource, .conflict]
        )
        XCTAssertThrowsError(try FactReviewPolicy.validateExplicitConfirmation(fact)) { error in
            XCTAssertEqual(error as? PatientAppError, .sourceRequired)
        }
    }

    func testTraceableFactRequiresExplicitReviewButCanThenConfirm() throws {
        let documentID = UUID()
        let fact = Fact(
            documentID: documentID,
            value: "Traceable",
            sourceReference: SourceReference(documentID: documentID, locator: "page:2"),
            state: .needsReview,
            confidence: 0.95
        )

        XCTAssertEqual(FactReviewPolicy.actionState(for: fact), .readyToConfirm)
        XCTAssertNoThrow(try FactReviewPolicy.validateExplicitConfirmation(fact))
        var confirmed = fact
        try confirmed.confirmAfterExplicitReview()
        XCTAssertEqual(FactReviewPolicy.actionState(for: confirmed), .confirmed)
    }
}
