import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

final class ReviewPresentationTests: XCTestCase {
    func testLowConfidenceAndMissingSourceAreExplicitReviewIssues() {
        let fact = Fact(
            documentID: UUID(),
            value: "Unverified result",
            state: .needsReview,
            confidence: 0.62
        )

        let expected: Set<FactReviewIssue> = [.lowConfidence, .missingSource]
        XCTAssertEqual(Set(fact.reviewIssues), expected)
        XCTAssertTrue(fact.needsReviewAttention)
    }

    func testRejectedMismatchedSourceExplainsConflictAndTraceability() {
        let documentID = UUID()
        let fact = Fact(
            documentID: documentID,
            value: "Conflicting result",
            sourceReference: SourceReference(documentID: UUID(), locator: "page:4"),
            state: .needsReview,
            reviewStatus: .rejected,
            confidence: 0.95
        )

        XCTAssertTrue(fact.reviewIssues.contains(.conflict))
        XCTAssertTrue(fact.reviewIssues.contains(.untraceable))
        XCTAssertFalse(fact.canAppearInDoctorView)
    }

    func testConfirmedTraceableFactHasNoReviewIssues() {
        let documentID = UUID()
        let fact = Fact(
            documentID: documentID,
            value: "Confirmed result",
            sourceReference: SourceReference(documentID: documentID, locator: "page:1"),
            state: .confirmed,
            wasExplicitlyReviewed: true,
            reviewStatus: .confirmed,
            confidence: 0.99
        )

        XCTAssertTrue(fact.reviewIssues.isEmpty)
        XCTAssertFalse(fact.needsReviewAttention)
        XCTAssertTrue(fact.canAppearInDoctorView)
    }
}
