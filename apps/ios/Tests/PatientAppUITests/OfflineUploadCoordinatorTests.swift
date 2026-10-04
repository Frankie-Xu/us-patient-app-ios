import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class OfflineUploadCoordinatorTests: XCTestCase {
    func testQueueMetadataPersistsAcrossCoordinatorRecreationWithoutBytes() async {
        let persistence = InMemoryUploadQueuePersistence()
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(pollsBeforeReady: 0))
        let clock = FixedImportClock(now: Date(timeIntervalSince1970: 1_700_000_000))
        let first = OfflineUploadCoordinator(
            client: client,
            persistence: persistence,
            clock: clock,
            isOnline: false
        )
        let request = ImportRequest(
            fileName: "synthetic.pdf",
            title: "Synthetic record",
            byteCount: 3,
            mediaType: "application/pdf",
            sha256: "sha",
            content: Data([1, 2, 3])
        )
        let id = first.enqueue(request)
        await first.persist()

        let second = OfflineUploadCoordinator(
            client: client,
            persistence: persistence,
            clock: clock,
            isOnline: false
        )
        await second.restore()

        XCTAssertEqual(second.items.map(\.id), [id])
        XCTAssertEqual(second.items.first?.state, .queued)
        XCTAssertEqual(second.items.first?.request.title, "Synthetic record")
        XCTAssertNil(second.items.first?.request.content)
    }

    func testDuplicateEnqueueIsIdempotent() {
        let client = DeterministicMockAPIClient()
        let coordinator = OfflineUploadCoordinator(client: client, isOnline: false)
        let request = ImportRequest(
            fileName: "same.pdf",
            title: "Same",
            byteCount: 1,
            mediaType: "application/pdf",
            sha256: "same",
            content: Data([1])
        )

        let first = coordinator.enqueue(request)
        let second = coordinator.enqueue(request)

        XCTAssertEqual(first, second)
        XCTAssertEqual(coordinator.items.count, 1)
    }

    func testOfflineStartDefersAndRecoveryResumesWithNotifications() async {
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(pollsBeforeReady: 0))
        let scheduler = RecordingBackgroundScheduler()
        let notifications = RecordingNotificationSink()
        let coordinator = OfflineUploadCoordinator(
            client: client,
            scheduler: scheduler,
            notifications: notifications,
            isOnline: false
        )
        let id = coordinator.enqueue(ImportRequest(
            fileName: "offline.txt",
            title: "Offline",
            byteCount: 1,
            content: Data([1])
        ))

        await coordinator.start()
        XCTAssertEqual(coordinator.items.first?.state, .queued)

        await coordinator.setOnline(true)

        XCTAssertEqual(coordinator.items.first?.id, id)
        XCTAssertEqual(coordinator.items.first?.state, .ready)
        let identifiers = await scheduler.identifiers\n        XCTAssertTrue(identifiers.contains(OfflineUploadCoordinator.backgroundTaskIdentifier))
        let events = await notifications.events
        XCTAssertTrue(events.contains(.wentOffline))
        XCTAssertTrue(events.contains(.networkRecovered))
        XCTAssertTrue(events.contains(.completed(id, "Offline")))
    }

    func testFailedUploadCanRetryUntilBoundedAttemptLimit() async {
        let client = DeterministicMockAPIClient(
            scenario: MockImportScenario(pollsBeforeReady: 0, failurePoint: .upload, failuresRemaining: 1)
        )
        let coordinator = OfflineUploadCoordinator(client: client, maxAttempts: 1)
        let id = coordinator.enqueue(ImportRequest(
            fileName: "retry.txt",
            title: "Retry",
            byteCount: 1,
            content: Data([1])
        ))

        await coordinator.start()

        XCTAssertEqual(coordinator.items.first?.state, .failed(.uploadFailed))
        await coordinator.retry(id: id)
        XCTAssertEqual(coordinator.items.first?.state, .failed(.uploadFailed))
        XCTAssertEqual(coordinator.items.first?.attempts, 1)
    }
}

@MainActor
final class OfflineDocumentCacheTests: XCTestCase {
    func testCachedDocumentExplicitlyReportsStaleAfterMaxAge() async {
        let cache = InMemoryOfflineDocumentCacheStore()
        let now = Date(timeIntervalSince1970: 1_700_000_100)
        let document = Document(
            title: "Synthetic cached document",
            createdAt: now.addingTimeInterval(-120),
            processingStatus: .ready
        )
        let entry = OfflineDocumentCacheEntry(
            document: document,
            facts: [Fact(documentID: document.id, value: "Synthetic fact")],
            cachedAt: now.addingTimeInterval(-30)
        )
        await cache.write(entry)

        let result = await cache.read(documentID: document.id, now: now, maxAge: .seconds(5))

        guard case let .stale(restored) = result else {
            return XCTFail("Expected stale cache result")
        }
        XCTAssertEqual(restored, entry)
        XCTAssertTrue(result.isStale)
        XCTAssertEqual(result.entry?.facts.count, 1)
    }
}

private struct FixedImportClock: ImportClock {
    let now: Date
    func sleep(for duration: Duration) async throws {}
}

private actor RecordingBackgroundScheduler: UploadBackgroundScheduler {
    private(set) var identifiers: [String] = []

    func schedule(identifier: String) async {
        identifiers.append(identifier)
    }
}

private actor RecordingNotificationSink: UploadQueueNotificationSink {
    private(set) var events: [UploadQueueNotification] = []

    func publish(_ notification: UploadQueueNotification) async {
        events.append(notification)
    }
}
