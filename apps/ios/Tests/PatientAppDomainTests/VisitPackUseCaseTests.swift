import XCTest
@testable import PatientAppDomain

final class VisitPackUseCaseTests: XCTestCase {
    func testLoadFiltersTopicsAndTasksForVisit() async throws {
        let topic = Topic(name: "Recent labs")
        let otherTopic = Topic(name: "Unrelated")
        let visit = Visit(title: "Primary care", topicIDs: [topic.id])
        let task = Task(title: "Bring questions", visitID: visit.id)
        let otherTask = Task(title: "Unrelated task")
        let client = DeterministicMockAPIClient(
            scenario: MockImportScenario(
                topics: [topic, otherTopic],
                visits: [visit],
                tasks: [task, otherTask]
            )
        )

        let pack = try await VisitPackUseCase(client: client).load(visitID: visit.id)

        XCTAssertEqual(pack.visit, visit)
        XCTAssertEqual(pack.topics, [topic])
        XCTAssertEqual(pack.tasks, [task])
    }

    func testMissingVisitPropagatesNotFound() async {
        do {
            _ = try await VisitPackUseCase(client: DeterministicMockAPIClient()).load(visitID: UUID())
            XCTFail("Expected missing visit error")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .notFound)
        } catch {
            XCTFail("Expected typed client error")
        }
    }
}
