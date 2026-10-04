import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class AppShellTests: XCTestCase {
    func testDefaultAppShellUsesDeterministicMock() async {
        let model = AppShellModel()
        await model.importFlow.start(ImportRequest(fileName: "synthetic.txt", title: "Synthetic"))

        if case .reviewRequired = model.importFlow.state {
            // The default shell remains usable without a configured live service.
        } else {
            XCTFail("Expected deterministic mock to produce review-required state")
        }
    }

    func testAppShellAcceptsAnInjectedClient() async {
        let model = AppShellModel(client: EmptyInjectedClient())
        await model.importFlow.start(ImportRequest(fileName: "empty.txt", title: "Injected"))

        if case .empty = model.importFlow.state {
            // The injected client supplied the empty result.
        } else {
            XCTFail("Expected the injected client to control the flow")
        }

        _ = AppShellView(client: EmptyInjectedClient())
    }

    func testLiveFactoryAssemblesTransportWithoutStartingARequest() throws {
        let configuration = LivePatientAPIClientConfiguration(
            baseURLProvider: StaticBaseURLProvider(baseURL: URL(string: "https://example.invalid")!),
            tokenProvider: StaticBearerTokenProvider(value: nil),
            requestIDProvider: FixedRequestIDProvider(value: "test-request")
        )

        let client = try PatientAPIClientFactory.makeLive(configuration: configuration)
        XCTAssertTrue(client is URLSessionPatientAPIClient)
    }
}

private struct EmptyInjectedClient: PatientAPIClient {
    private let documentID = UUID()

    func createImport(_ request: ImportRequest) async throws -> ImportTicket {
        ImportTicket(documentID: documentID, title: request.title)
    }

    func upload(_ request: UploadRequest) async throws -> UploadReceipt {
        UploadReceipt(ticketID: request.ticketID, documentID: documentID)
    }

    func processingStatus(documentID: UUID) async throws -> ProcessingStatus { .ready }
    func facts(documentID: UUID) async throws -> [Fact] { [] }
    func editFact(_ command: FactEditCommand) async throws -> Fact { throw PatientAppError.factNotFound }
    func confirmFact(_ command: FactReviewCommand) async throws -> Fact { throw PatientAppError.factNotFound }
}
