import XCTest
@testable import PatientAppDomain

final class SessionStoreTests: XCTestCase {
    func testAccountSwitchChangesEpochAndPurgesPreviousCache() async {
        let cache = InMemoryProtectedCache()
        let store = InMemorySessionStore(cache: cache)
        let first = await store.beginSession(identifier: "account-a")
        await cache.setData(Data("old".utf8), forKey: "history", session: first)

        let second = await store.beginSession(identifier: "account-b")
        XCTAssertNotEqual(first, second)
        XCTAssertEqual(second.epoch, first.epoch + 1)
        let oldData = await cache.data(forKey: "history", session: first)
        let secondIsCurrent = await store.isCurrent(second)
        let firstIsCurrent = await store.isCurrent(first)
        XCTAssertNil(oldData)
        XCTAssertTrue(secondIsCurrent)
        XCTAssertFalse(firstIsCurrent)
    }

    func testLogoutClearsActiveSessionAndAllCache() async {
        let cache = InMemoryProtectedCache()
        let store = InMemorySessionStore(cache: cache)
        let context = await store.beginSession(identifier: "account-a")
        await cache.setData(Data("old".utf8), forKey: "history", session: context)

        await store.logout()
        let currentSession = await store.currentSession()
        let oldData = await cache.data(forKey: "history", session: context)
        XCTAssertNil(currentSession)
        XCTAssertNil(oldData)
    }
}
