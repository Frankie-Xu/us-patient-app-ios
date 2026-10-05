import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class RuntimeCompositionTests: XCTestCase {
    func testRuntimeRestoresSessionAndUsesProtectedCacheBoundary() async {
        let model = PatientAppRuntime.makeModel()
        let signedIn = await model.signIn(identifier: "fixture-account")
        guard case let .signedIn(session) = signedIn else {
            return XCTFail("local runtime should sign in through the session boundary")
        }
        XCTAssertEqual(session.identifier, "fixture-account")
        let current = await model.sessionStore.currentSession()
        XCTAssertNotNil(current)
        await model.logout()
        let state = await model.authSession.authState()
        XCTAssertEqual(state, .signedOut)
    }

    func testLocalURLSessionFixtureCompletesSyntheticImport() async {
        let model = PatientAppRuntime.makeModel()
        _ = await model.signIn(identifier: "fixture-account")
        let content = Data("synthetic fixture content".utf8)
        await model.importFlow.start(
            ImportRequest(
                fileName: "synthetic-record.txt",
                title: "Synthetic record",
                byteCount: content.count,
                mediaType: "text/plain",
                sha256: String(repeating: "0", count: 64),
                content: content
            )
        )
        guard case let .reviewRequired(snapshot) = model.importFlow.state else {
            return XCTFail("fixture upload should produce a reviewable snapshot")
        }
        XCTAssertEqual(snapshot.facts.count, 1)
        XCTAssertEqual(snapshot.facts.first?.sourceReference?.locator, "page:1")
        XCTAssertLessThan(snapshot.facts.first?.confidence ?? 0, 1.0)
    }
}
