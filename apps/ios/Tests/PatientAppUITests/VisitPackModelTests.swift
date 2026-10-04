import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class VisitPackModelTests: XCTestCase {
    func testModelLoadsPackAndCanReset() async {
        let topic = Topic(name: "Medication questions")
        let visit = Visit(title: "Follow-up", topicIDs: [topic.id])
        let task = Task(title: "Bring medication list", visitID: visit.id)
        let model = VisitPackModel(
            client: DeterministicMockAPIClient(
                scenario: MockImportScenario(topics: [topic], visits: [visit], tasks: [task])
            )
        )

        await model.load(visitID: visit.id)

        guard case let .loaded(pack) = model.state else {
            return XCTFail("Expected loaded visit pack")
        }
        XCTAssertEqual(pack.topics, [topic])
        XCTAssertEqual(pack.tasks, [task])

        model.reset()
        XCTAssertEqual(model.state, .idle)
    }

    func testModelMapsMissingVisitToTypedFailure() async {
        let model = VisitPackModel(client: DeterministicMockAPIClient())
        await model.load(visitID: UUID())
        XCTAssertEqual(model.state, .failed(.notFound))
    }
}
