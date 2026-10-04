import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class CacheLifecycleModelTests: XCTestCase {
    func testAccountHistoryCacheIsSessionScopedAndLogoutHidesOldData() async {
        let cache = InMemoryProtectedCache()
        let store = InMemorySessionStore(cache: cache)
        let session = await store.beginSession(identifier: "account-a")
        let oldVisit = Visit(title: "Cached follow-up")
        let source = DeterministicMockAPIClient(scenario: MockImportScenario(visits: [oldVisit]))
        let model = AccountHistoryModel(client: source, cache: cache, sessionStore: store)

        await model.load()
        guard case let .loaded(snapshot) = model.state else { return XCTFail("Expected initial history") }
        XCTAssertEqual(snapshot.visits, [oldVisit])
        let cachedData = await cache.data(forKey: "account-history-v1", session: session)
        XCTAssertNotNil(cachedData)

        await model.logout()
        XCTAssertEqual(model.state, .idle)
        let purgedData = await cache.data(forKey: "account-history-v1", session: session)
        XCTAssertNil(purgedData)
    }

    func testOldAccountHistoryRequestCannotWriteAfterLogout() async {
        let cache = InMemoryProtectedCache()
        let store = InMemorySessionStore(cache: cache)
        _ = await store.beginSession(identifier: "account-a")
        let model = AccountHistoryModel(repository: DelayedHistoryRepository(), cache: cache, sessionStore: store)

        let request = _Concurrency.Task { await model.load() }
        try? await _Concurrency.Task.sleep(for: .milliseconds(10))
        await model.logout()
        await request.value

        XCTAssertEqual(model.state, .idle)
        let currentSession = await store.currentSession()
        XCTAssertNil(currentSession)
    }

    func testOldAccountHistoryRequestCannotWriteAfterAccountSwitch() async {
        let cache = InMemoryProtectedCache()
        let store = InMemorySessionStore(cache: cache)
        _ = await store.beginSession(identifier: "account-a")
        let repository = DelayedHistoryRepository()
        let model = AccountHistoryModel(repository: repository, cache: cache, sessionStore: store)

        let request = _Concurrency.Task { await model.load() }
        await repository.waitUntilStarted()
        _ = await store.beginSession(identifier: "account-b")
        await request.value

        XCTAssertEqual(model.state, .idle)
    }

    func testOldVisitCreationCannotReappearAfterLogout() async {
        let store = InMemorySessionStore()
        _ = await store.beginSession(identifier: "account-a")
        let model = VisitPreparationModel(client: DelayedVisitClient(), sessionStore: store)

        let request = _Concurrency.Task { await model.createVisit(VisitCreateRequest(title: "Old visit")) }
        try? await _Concurrency.Task.sleep(for: .milliseconds(10))
        await model.logout()
        await request.value

        XCTAssertEqual(model.visitState, .empty)
    }
}

private actor DelayedHistoryRepository: AccountHistoryRepository {
    private var hasStarted = false
    private var startedWaiters: [CheckedContinuation<Void, Never>] = []

    func waitUntilStarted() async {
        if hasStarted { return }
        await withCheckedContinuation { continuation in
            startedWaiters.append(continuation)
        }
    }

    private func markStarted() {
        guard !hasStarted else { return }
        hasStarted = true
        let waiters = startedWaiters
        startedWaiters.removeAll(keepingCapacity: false)
        waiters.forEach { $0.resume() }
    }

    func topics() async throws -> [Topic] {
        markStarted()
        try await _Concurrency.Task.sleep(for: .milliseconds(60))
        return []
    }

    func visits() async throws -> [Visit] {
        markStarted()
        try await _Concurrency.Task.sleep(for: .milliseconds(60))
        return [Visit(title: "Old account visit")]
    }

    func tasks() async throws -> [PatientAppDomain.Task] {
        markStarted()
        try await _Concurrency.Task.sleep(for: .milliseconds(60))
        return []
    }
}

private actor DelayedVisitClient: PatientAPIClient {
    func createImport(_ request: ImportRequest) async throws -> ImportTicket { throw PatientAPIClientError.unsupported(.topicCreationNotInClient) }
    func upload(_ request: UploadRequest) async throws -> UploadReceipt { throw PatientAPIClientError.unsupported(.topicCreationNotInClient) }
    func processingStatus(documentID: UUID) async throws -> ProcessingStatus { .ready }
    func facts(documentID: UUID) async throws -> [Fact] { [] }
    func editFact(_ command: FactEditCommand) async throws -> Fact { throw PatientAppError.factNotFound }
    func confirmFact(_ command: FactReviewCommand) async throws -> Fact { throw PatientAppError.factNotFound }

    func createVisit(_ request: VisitCreateRequest) async throws -> Visit {
        try await _Concurrency.Task.sleep(for: .milliseconds(60))
        return Visit(title: request.title)
    }
}
