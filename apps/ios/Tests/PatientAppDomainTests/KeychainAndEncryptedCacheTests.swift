import XCTest
@testable import PatientAppDomain

final class KeychainAndEncryptedCacheTests: XCTestCase {
    func testSessionStoreRestoresAndPurgesOnAccountSwitchAndLogout() async {
        let credentialStore = InMemorySessionCredentialStore()
        let cache = InMemoryProtectedCache()
        let firstStore = KeychainSessionStore(credentialStore: credentialStore, cache: cache)
        let first = await firstStore.beginSession(identifier: "account-a")
        await cache.setData(Data("old".utf8), forKey: "history", session: first)

        let secondStore = KeychainSessionStore(credentialStore: credentialStore, cache: cache)
        let restored = await secondStore.restore()
        XCTAssertEqual(restored, .signedIn(first))
        let second = await secondStore.switchAccount(identifier: "account-b")
        guard case let .signedIn(secondContext) = second else { return XCTFail("Expected account-b") }
        XCTAssertEqual(secondContext.epoch, first.epoch + 1)
        let oldData = await cache.data(forKey: "history", session: first)
        XCTAssertNil(oldData)

        await secondStore.logout()
        let persisted = await credentialStore.read()
        let current = await secondStore.currentSession()
        XCTAssertNil(persisted)
        XCTAssertNil(current)
    }

    func testEncryptedCacheStoresEnvelopeAndRoundTripsMetadata() async {
        let storage = InMemoryOfflineMetadataStorage()
        let cipher = DeterministicOfflineMetadataCipher()
        let cache = EncryptedOfflineDocumentCacheStore(storage: storage, cipher: cipher)
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let document = Document(title: "Synthetic record", createdAt: now, processingStatus: .ready)
        let entry = OfflineDocumentCacheEntry(
            document: document,
            facts: [Fact(documentID: document.id, value: "synthetic fact", createdAt: now, updatedAt: now)],
            cachedAt: now
        )

        await cache.write(entry)
        let raw = await cache.rawEnvelopeData(documentID: document.id)
        XCTAssertNotNil(raw)
        XCTAssertFalse(raw?.contains(Data("Synthetic record".utf8)) ?? true)

        let result = await cache.read(documentID: document.id, now: now, maxAge: .seconds(5))
        XCTAssertEqual(result.entry, entry)
    }

    func testWrongCipherKeyTreatsEnvelopeAsCacheMiss() async {
        let storage = InMemoryOfflineMetadataStorage()
        let writer = EncryptedOfflineDocumentCacheStore(
            storage: storage,
            cipher: DeterministicOfflineMetadataCipher(key: Data("writer".utf8))
        )
        let reader = EncryptedOfflineDocumentCacheStore(
            storage: storage,
            cipher: DeterministicOfflineMetadataCipher(key: Data("reader".utf8))
        )
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let document = Document(title: "Synthetic record", createdAt: now, processingStatus: .ready)
        await writer.write(OfflineDocumentCacheEntry(document: document, cachedAt: now))

        let result = await reader.read(documentID: document.id, now: now, maxAge: .seconds(5))
        XCTAssertEqual(result, .missing)
    }
}
