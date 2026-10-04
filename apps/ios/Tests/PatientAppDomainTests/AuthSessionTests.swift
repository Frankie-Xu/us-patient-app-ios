import XCTest
@testable import PatientAppDomain

final class AuthSessionTests: XCTestCase {
    func testSignInRestoreSwitchAndLogoutStates() async {
        let cache = InMemoryProtectedCache()
        let session = InMemorySessionStore(cache: cache)

        let initial = await session.authState()
        let signedIn = await session.signIn(identifier: "account-a")
        let restored = await session.restore()
        let switched = await session.switchAccount(identifier: "account-b")
        await session.logout()
        let finalState = await session.authState()

        XCTAssertEqual(initial, .signedOut)
        guard case let .signedIn(first) = signedIn,
              case let .signedIn(restoredContext) = restored,
              case let .signedIn(second) = switched else {
            return XCTFail("Expected signed-in states")
        }
        XCTAssertEqual(first, restoredContext)
        XCTAssertNotEqual(first, second)
        XCTAssertEqual(finalState, .signedOut)
    }

    func testExpirePurgesCacheAndRequiresFreshEpoch() async {
        let cache = InMemoryProtectedCache()
        let session = InMemorySessionStore(cache: cache)
        guard case let .signedIn(context) = await session.signIn(identifier: "account-a") else {
            return XCTFail("Expected signed-in state")
        }
        await cache.setData(Data("old".utf8), forKey: "history", session: context)

        await session.expire()
        let state = await session.authState()
        let current = await session.currentSession()
        let oldData = await cache.data(forKey: "history", session: context)
        let oldIsCurrent = await session.isCurrent(context)
        let restored = await session.restore()
        let signedInAgain = await session.signIn(identifier: "account-a")

        XCTAssertEqual(state, .expired)
        XCTAssertNil(current)
        XCTAssertNil(oldData)
        XCTAssertFalse(oldIsCurrent)
        XCTAssertEqual(restored, .expired)
        guard case let .signedIn(newContext) = signedInAgain else {
            return XCTFail("Expected a fresh signed-in state")
        }
        XCTAssertEqual(newContext.identifier, context.identifier)
        XCTAssertGreaterThan(newContext.epoch, context.epoch)
    }

    func testConcurrentAccountSwitchesProduceDistinctEpochs() async {
        let session = InMemorySessionStore()
        async let first = session.switchAccount(identifier: "account-a")
        async let second = session.switchAccount(identifier: "account-b")
        let results = await [first, second]
        let contexts = results.compactMap { state -> SessionContext? in
            guard case let .signedIn(context) = state else { return nil }
            return context
        }
        let current = await session.currentSession()

        XCTAssertEqual(contexts.count, 2)
        XCTAssertEqual(Set(contexts.map(\.epoch)).count, 2)
        XCTAssertEqual(current?.epoch, 2)
        XCTAssertTrue(current.map { contexts.contains($0) } ?? false)
    }
}
