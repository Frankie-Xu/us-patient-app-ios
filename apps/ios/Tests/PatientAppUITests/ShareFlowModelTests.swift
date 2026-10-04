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
}
