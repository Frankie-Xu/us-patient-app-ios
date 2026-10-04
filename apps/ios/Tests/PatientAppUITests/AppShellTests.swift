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

    func testAuthRestoreRetryAndExpiryStatesAreExposed() async {
        let model = AppShellModel()

        XCTAssertEqual(model.authState, .signedOut)
        let initialRestore = await model.restoreSession()
        XCTAssertEqual(initialRestore, .signedOut)
        guard case let .signedIn(context) = await model.signIn(identifier: "account-a") else {
            return XCTFail("Expected signed-in state")
        }
        await model.expireSession()
        XCTAssertEqual(model.authState, .expired)
        let expiredRestore = await model.retryRestore()
        XCTAssertEqual(expiredRestore, .expired)
        guard case let .signedIn(restoredContext) = await model.signIn(identifier: "account-a") else {
            return XCTFail("Expected retry sign-in to restore a live session")
        }
        XCTAssertGreaterThan(restoredContext.epoch, context.epoch)
        await model.logout()
        XCTAssertEqual(model.authState, .signedOut)
    }

    func testAccountSwitchUsesInjectedAuthSessionAndPurgesCache() async {
        let cache = InMemoryProtectedCache()
        let authSession = InMemorySessionStore(cache: cache)
        let model = AppShellModel(protectedCache: cache, authSession: authSession)

        guard case let .signedIn(first) = await model.signIn(identifier: "account-a") else {
            return XCTFail("Expected first account to sign in")
        }
        await cache.setData(Data("old".utf8), forKey: "history", session: first)

        guard case let .signedIn(second) = await model.switchAccount(identifier: "account-b") else {
            return XCTFail("Expected account switch to sign in")
        }
        let oldData = await cache.data(forKey: "history", session: first)
        let current = await authSession.currentSession()

        XCTAssertNil(oldData)
        XCTAssertEqual(current, second)
        XCTAssertEqual(model.authState, .signedIn(second))
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
