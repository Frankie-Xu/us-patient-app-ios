import XCTest
@testable import PatientAppDomain

final class DomainTests: XCTestCase {
    func testFactWithoutSourceCannotBeConfirmed() throws {
        var fact = Fact(documentID: UUID(), value: "synthetic value")
        try fact.markNeedsReview()
        XCTAssertThrowsError(try fact.confirmAfterExplicitReview())
        XCTAssertFalse(fact.canAppearInDoctorView)
    }

    func testUserInputCanBeConfirmedAfterExplicitReview() throws {
        var fact = Fact(documentID: UUID(), value: "synthetic value", isUserInput: true)
        try fact.markNeedsReview()
        try fact.confirmAfterExplicitReview()
        XCTAssertTrue(fact.wasExplicitlyReviewed)
        XCTAssertTrue(fact.canAppearInDoctorView)
    }

    func testSourcedFactRequiresExplicitReviewBeforeConfirmation() throws {
        let documentID = UUID()
        let source = SourceReference(documentID: documentID, locator: "page:1")
        var fact = Fact(documentID: documentID, value: "synthetic value", sourceReference: source)
        try fact.markNeedsReview()
        XCTAssertThrowsError(try fact.transition(to: .confirmed))
        try fact.confirmAfterExplicitReview()
        XCTAssertEqual(fact.state, .confirmed)
    }

    func testConfirmedFactWithoutReviewCannotAppearInDoctorView() {
        let documentID = UUID()
        let source = SourceReference(documentID: documentID, locator: "page:1")
        let fact = Fact(documentID: documentID, value: "synthetic value", sourceReference: source, state: .confirmed)
        XCTAssertFalse(fact.canAppearInDoctorView)
    }

    func testMismatchedSourceReferenceIsNotTraceable() {
        let fact = Fact(
            documentID: UUID(),
            value: "synthetic value",
            sourceReference: SourceReference(documentID: UUID(), locator: "page:1")
        )
        XCTAssertFalse(fact.isTraceable)
    }

    func testLifecycleOnlyAllowsForwardTransitionsAndRevocationIsNotErasure() throws {
        var document = Document(title: "Synthetic document")
        try document.transition(to: .needsReview)
        try document.transition(to: .confirmed)
        try document.transition(to: .shared)
        XCTAssertThrowsError(try document.transition(to: .draft))

        var share = ShareVersion(documentID: document.id, version: 1)
        try share.revoke()
        XCTAssertEqual(share.state, .revoked)
        XCTAssertNotNil(share.revokedAt)
    }
}
