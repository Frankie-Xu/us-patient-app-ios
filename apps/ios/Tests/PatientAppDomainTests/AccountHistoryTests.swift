import XCTest
@testable import PatientAppDomain

final class AccountHistoryTests: XCTestCase {
    func testUseCaseAggregatesTopicsVisitsAndTasks() async throws {
        let topic = Topic(name: "Recent labs")
        let visit = Visit(title: "Primary care")
        let task = Task(title: "Bring questions", visitID: visit.id)
        let snapshot = try await AccountHistoryUseCase(repository: StubRepository(topics: [topic], visits: [visit], tasks: [task])).load()

        XCTAssertEqual(snapshot.topics, [topic])
        XCTAssertEqual(snapshot.visits, [visit])
        XCTAssertEqual(snapshot.tasks, [task])
        XCTAssertFalse(snapshot.isEmpty)
    }

    func testRepositoryPropagatesTypedClientErrors() async {
        let repository = FailingRepository(error: .unauthorized)
        do {
            _ = try await AccountHistoryUseCase(repository: repository).load()
            XCTFail("Expected account history error")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .unauthorized)
        } catch {
            XCTFail("Expected typed client error")
        }
    }
}

private struct StubRepository: AccountHistoryRepository {
    let topics: [Topic]
    let visits: [Visit]
    let tasks: [Task]

    func topics() async throws -> [Topic] { topics }
    func visits() async throws -> [Visit] { visits }
    func tasks() async throws -> [Task] { tasks }
}

private struct FailingRepository: AccountHistoryRepository {
    let error: PatientAPIClientError

    func topics() async throws -> [Topic] { throw error }
    func visits() async throws -> [Visit] { throw error }
    func tasks() async throws -> [Task] { throw error }
}
