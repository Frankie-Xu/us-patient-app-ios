import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class ShareFlowModelTests: XCTestCase {
    func testVisitShareCanBeCreatedAndRevoked() async {
        let now = Date(timeIntervalSince1970: 1_000)
        let model = ShareFlowModel(client: DeterministicMockAPIClient(), now: { now })
        let visit = Visit(id: UUID(), title: "Synthetic follow-up", version: 2)

        await model.createVisitShare(for: visit)

        guard case let .created(creation) = model.state else {
            return XCTFail("Expected a created share")
        }
        XCTAssertEqual(creation.share.resourceID, visit.id)
        XCTAssertEqual(creation.share.version, visit.version)

        await model.revoke()

        guard case let .revoked(version) = model.state else {
            return XCTFail("Expected a revoked share")
        }
        XCTAssertEqual(version.state, .revoked)
    }

    func testResetClearsTokenAfterSessionBoundary() async {
        let model = ShareFlowModel(client: DeterministicMockAPIClient())
        await model.createVisitShare(for: Visit(title: "Synthetic visit"))

        XCTAssertNotNil(model.shareCreation)
        model.reset()

        XCTAssertEqual(model.state, .idle)
        XCTAssertNil(model.shareCreation)
    }

    func testDocumentShareUsesPinnedVersionAndExportsPDF() async throws {
        let now = Date(timeIntervalSince1970: 1_000)
        let model = ShareFlowModel(client: DeterministicMockAPIClient(), now: { now })
        let documentID = UUID()

        await model.createDocumentShare(documentID: documentID, version: 3)

        guard case let .created(creation) = model.state else {
            return XCTFail("Expected a document share")
        }
        XCTAssertEqual(creation.share.resourceType, .document)
        XCTAssertEqual(creation.share.resourceID, documentID)
        XCTAssertEqual(creation.share.version, 3)

        let artifact = try await model.exportPDF(documentID: documentID, version: 3)
        XCTAssertEqual(artifact.documentVersion, 3)
        XCTAssertEqual(artifact.contentType, "application/pdf")
    }

    func testCreateRefreshesActiveStatusAndExposesStableCopy() async {
        let model = ShareFlowModel(client: DeterministicMockAPIClient())

        await model.createDocumentShare(documentID: UUID(), version: 1)

        guard case let .loaded(status) = model.statusState else {
            return XCTFail("Expected an active status refresh after creation")
        }
        XCTAssertEqual(status.state, .active)
        XCTAssertTrue(status.isAccessible)
        XCTAssertEqual(model.statusLabel, "Active")
        XCTAssertEqual(model.statusMessage, "This share link is active.")
    }

    func testStatusFailureCanRetryWithoutCreatingAnotherShare() async {
        let client = DeterministicMockAPIClient(
            scenario: MockImportScenario(failurePoint: .shareStatus)
        )
        let model = ShareFlowModel(client: client)
        let documentID = UUID()

        await model.createDocumentShare(documentID: documentID, version: 2)

        guard case .failed = model.statusState else {
            return XCTFail("Expected the first status lookup to fail")
        }
        let tokenBeforeRetry = model.shareCreation?.token
        XCTAssertEqual(model.statusLabel, "Status unavailable")

        await model.retryStatus()

        guard case let .loaded(status) = model.statusState else {
            return XCTFail("Expected retry to load the share status")
        }
        XCTAssertEqual(status.state, .active)
        XCTAssertEqual(model.shareCreation?.token, tokenBeforeRetry)
    }

    func testRefreshStatusSurfacesExpiredAndRevokedStates() async {
        // The request is valid against this injected clock while already expired
        // relative to the mock server's wall clock.
        let model = ShareFlowModel(
            client: DeterministicMockAPIClient(),
            now: { Date(timeIntervalSince1970: 0) }
        )

        await model.createDocumentShare(documentID: UUID(), version: 1)

        guard case let .loaded(expired) = model.statusState else {
            return XCTFail("Expected an expired status")
        }
        XCTAssertEqual(expired.state, .expired)
        XCTAssertFalse(expired.isAccessible)
        XCTAssertEqual(model.statusLabel, "Expired")

        await model.revoke()

        guard case let .loaded(revoked) = model.statusState else {
            return XCTFail("Expected a revoked status")
        }
        XCTAssertEqual(revoked.state, .revoked)
        XCTAssertEqual(model.statusLabel, "Revoked")
        XCTAssertEqual(model.statusMessage, "This share link has been revoked.")
    }
}
