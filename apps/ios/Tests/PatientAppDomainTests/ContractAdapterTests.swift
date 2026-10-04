import XCTest
@testable import PatientAppDomain

final class ContractAdapterTests: XCTestCase {
    private let documentID = UUID()
    private let now = Date(timeIntervalSince1970: 1_700_000_000)

    func testDocumentAndJobMapNullableFieldsAndVersions() throws {
        let document = try ContractDocumentPayload(
            filename: "synthetic.pdf", mediaType: "application/pdf", sizeBytes: 42, sha256: String(repeating: "a", count: 64),
            id: documentID, ownerID: "owner", sourceType: .uploadedDocument, status: .ready, version: 3,
            createdAt: now, updatedAt: now, deletedAt: nil
        ).domainValue()
        XCTAssertEqual(document.title, "synthetic.pdf")
        XCTAssertEqual(document.processingStatus, .ready)
        XCTAssertEqual(document.version, 3)
        XCTAssertNil(document.deletedAt)

        let job = try ContractProcessingJobPayload(
            id: UUID(), ownerID: "owner", documentID: documentID, jobType: .extractFacts, status: .succeeded,
            idempotencyKey: "key", attempt: 1, errorCode: nil, createdAt: now, updatedAt: now
        ).domainValue()
        XCTAssertEqual(job.status, .succeeded)
        XCTAssertNil(job.errorCode)
    }

    func testFactMappingPreservesNullableTopicAndReviewRequiredSemantics() throws {
        let payload = ContractFactPayload(
            label: "Synthetic label", value: "Synthetic value", sourceRef: nil, sourceType: .userInput,
            confidence: 1, documentID: documentID, topicID: nil, id: UUID(), ownerID: "owner",
            reviewStatus: .unreviewed, version: 4, createdAt: now, updatedAt: now
        )
        let fact = try payload.domainValue()
        XCTAssertNil(fact.topicID)
        XCTAssertNil(fact.sourceReference)
        XCTAssertTrue(fact.isUserInput)
        XCTAssertEqual(fact.reviewStatus, .unreviewed)
        XCTAssertEqual(fact.state, .needsReview)
        XCTAssertFalse(fact.canAppearInDoctorView)
    }

    func testConfirmedFactNeedsSourceAndMapsToDoctorView() throws {
        let payload = ContractFactPayload(
            label: "Synthetic label", value: "Synthetic value", sourceRef: "page:2", sourceType: .ocr,
            confidence: 0.8, documentID: documentID, topicID: UUID(), id: UUID(), ownerID: "owner",
            reviewStatus: .confirmed, version: 2, createdAt: now, updatedAt: now
        )
        let fact = try payload.domainValue()
        XCTAssertEqual(fact.state, .confirmed)
        XCTAssertEqual(fact.reviewStatus, .confirmed)
        XCTAssertTrue(fact.canAppearInDoctorView)

        let missingSource = ContractFactPayload(
            label: "Synthetic label", value: "Synthetic value", sourceRef: nil, sourceType: .ocr,
            confidence: 0.8, documentID: documentID, topicID: nil, id: UUID(), ownerID: "owner",
            reviewStatus: .confirmed, version: 2, createdAt: now, updatedAt: now
        )
        XCTAssertThrowsError(try missingSource.domainValue()) { error in
            XCTAssertEqual(error as? PatientAppError, .invalidContractData(.missingSourceReference))
        }
    }

    func testNullableDocumentIDIsRejectedWithoutInventingIdentity() {
        let payload = ContractFactPayload(
            label: "Synthetic label", value: "Synthetic value", sourceRef: "input:1", sourceType: .userInput,
            confidence: 1, documentID: nil, topicID: nil, id: UUID(), ownerID: "owner",
            reviewStatus: .unreviewed, version: 1, createdAt: now, updatedAt: now
        )
        XCTAssertThrowsError(try payload.domainValue()) { error in
            XCTAssertEqual(error as? PatientAppError, .invalidContractData(.missingDocumentID))
        }
    }

    func testReviewMappingCarriesIfMatchVersionAndRequiresConfirmedStatus() throws {
        let command = try ContractReviewRequest(reviewStatus: .confirmed, ifMatchVersion: 7).domainCommand(documentID: documentID, factID: UUID())
        XCTAssertEqual(command.ifMatchVersion, 7)
        XCTAssertThrowsError(try ContractReviewRequest(reviewStatus: .inReview, ifMatchVersion: 7).domainCommand(documentID: documentID, factID: UUID())) { error in
            XCTAssertEqual(error as? PatientAppError, .reviewRequired)
        }
    }

    func testShareMappingPreservesResourceVersionAndNullableRevocation() throws {
        let payload = ContractShareVersionPayload(
            id: UUID(), ownerID: "owner", resourceType: .visit, resourceID: documentID, resourceVersion: 9,
            expiresAt: now.addingTimeInterval(3_600), status: .active, revokedAt: nil, createdAt: now
        )
        let share = try payload.domainValue()
        XCTAssertEqual(share.resourceType, .visit)
        XCTAssertEqual(share.resourceID, documentID)
        XCTAssertEqual(share.version, 9)
        XCTAssertNil(share.revokedAt)
        XCTAssertEqual(share.state, .shared)
    }
}
