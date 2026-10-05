import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class UploadQueueModelTests: XCTestCase {
    func testQueueProcessesItemsSequentiallyAndPublishesCompletionProgress() async throws {
        let client = DeterministicMockAPIClient(
            scenario: MockImportScenario(pollsBeforeReady: 0)
        )
        let queue = UploadQueueModel(client: client)
        let firstID = queue.enqueue(ImportRequest(fileName: "first.txt", title: "First"))
        let secondID = queue.enqueue(ImportRequest(fileName: "second.txt", title: "Second"))

        await queue.start()

        XCTAssertFalse(queue.isRunning)
        XCTAssertEqual(queue.items.map(\.id), [firstID, secondID])
        XCTAssertTrue(queue.items.allSatisfy { $0.state == .ready && $0.progress == 1 })
        XCTAssertTrue(queue.items.allSatisfy { $0.attempts == 1 && $0.snapshot != nil })
    }

    func testFailedItemCanBeRetriedWithoutReenqueuing() async throws {
        let client = DeterministicMockAPIClient(
            scenario: MockImportScenario(pollsBeforeReady: 0, failurePoint: .upload)
        )
        let queue = UploadQueueModel(client: client)
        let id = queue.enqueue(ImportRequest(fileName: "retry.txt", title: "Retry"))

        await queue.start()

        guard let failed = queue.items.first else { return XCTFail("Expected queued item") }
        XCTAssertEqual(failed.id, id)
        XCTAssertEqual(failed.state, .failed(.uploadFailed))
        XCTAssertTrue(queue.hasRetryableFailures)
        XCTAssertEqual(failed.attempts, 1)

        await queue.retry(id: id)

        guard let retried = queue.items.first else { return XCTFail("Expected retried item") }
        XCTAssertEqual(retried.state, .ready)
        XCTAssertEqual(retried.progress, 1)
        XCTAssertEqual(retried.attempts, 2)
        XCTAssertFalse(queue.hasRetryableFailures)
    }
}
