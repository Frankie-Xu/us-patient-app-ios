import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class AppShellSessionTests: XCTestCase {
    func testSignInAndLogoutExposeSessionState() async {
        let model = AppShellModel(client: DeterministicMockAPIClient())

        _ = await model.signIn(identifier: "patient@example.test")

        guard case let .signedIn(session) = model.authState else {
            return XCTFail("Expected a signed-in session")
        }
        XCTAssertEqual(session.identifier, "patient@example.test")

        await model.logout()

        XCTAssertEqual(model.authState, .signedOut)
        XCTAssertEqual(model.documentHistory.state, .idle)
    }

    func testSwitchAccountCreatesASeparateSessionEpoch() async {
        let model = AppShellModel(client: DeterministicMockAPIClient())

        _ = await model.signIn(identifier: "first@example.test")
        guard case let .signedIn(first) = model.authState else {
            return XCTFail("Expected first session")
        }

        _ = await model.switchAccount(identifier: "second@example.test")

        guard case let .signedIn(second) = model.authState else {
            return XCTFail("Expected second session")
        }
        XCTAssertEqual(second.identifier, "second@example.test")
        XCTAssertGreaterThan(second.epoch, first.epoch)
    }
}
