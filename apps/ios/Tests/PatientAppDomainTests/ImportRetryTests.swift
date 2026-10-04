import XCTest
@testable import PatientAppDomain

final class ImportRetryTests: XCTestCase {
    func testProcessingUsesExponentialBackoffAndEventuallySucceeds() async throws {
        let clock = RecordingImportClock()
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(pollsBeforeReady: 3))
        let policy = ImportRetryPolicy(maxAttempts: 5, maxDuration: .seconds(30), initialDelay: .seconds(1), maximumDelay: .seconds(4))

        _ = try await ImportUseCase(client: client, clock: clock, retryPolicy: policy).run(ImportRequest(fileName: "synthetic.txt", title: "Synthetic"))

        XCTAssertEqual(clock.sleeps, [.seconds(1), .seconds(2), .seconds(4)])
    }

    func testProcessingFailedMapsToStableErrorWithoutRetrying() async {
        let clock = RecordingImportClock()
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(terminalProcessingStatus: .failed))

        do {
            _ = try await ImportUseCase(client: client, clock: clock).run(ImportRequest(fileName: "synthetic.txt", title: "Synthetic"))
            XCTFail("Expected processing failure")
        } catch let error as PatientAppError {
            XCTAssertEqual(error, .processingFailed)
            XCTAssertTrue(clock.sleeps.isEmpty)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testMaximumAttemptsMapToTimeout() async {
        let clock = RecordingImportClock()
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(pollsBeforeReady: 100))
        let policy = ImportRetryPolicy(maxAttempts: 3, maxDuration: .seconds(30), initialDelay: .seconds(1), maximumDelay: .seconds(4))

        do {
            _ = try await ImportUseCase(client: client, clock: clock, retryPolicy: policy).run(ImportRequest(fileName: "synthetic.txt", title: "Synthetic"))
            XCTFail("Expected timeout")
        } catch let error as PatientAppError {
            XCTAssertEqual(error, .processingTimeout)
            XCTAssertEqual(clock.sleeps, [.seconds(1), .seconds(2)])
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testTotalDurationMapsToTimeoutBeforeNextSleep() async {
        let clock = RecordingImportClock()
        let client = DeterministicMockAPIClient(scenario: MockImportScenario(pollsBeforeReady: 100))
        let policy = ImportRetryPolicy(maxAttempts: 10, maxDuration: .seconds(2), initialDelay: .seconds(1), maximumDelay: .seconds(4))

        do {
            _ = try await ImportUseCase(client: client, clock: clock, retryPolicy: policy).run(ImportRequest(fileName: "synthetic.txt", title: "Synthetic"))
            XCTFail("Expected timeout")
        } catch let error as PatientAppError {
            XCTAssertEqual(error, .processingTimeout)
            XCTAssertEqual(clock.sleeps, [.seconds(1)])
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testTaskCancellationMapsToStableError() async {
        let client = CancellationProcessingClient()

        do {
            _ = try await ImportUseCase(client: client).run(ImportRequest(fileName: "synthetic.txt", title: "Synthetic"))
            XCTFail("Expected cancellation")
        } catch let error as PatientAppError {
            XCTAssertEqual(error, .processingCancelled)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }
}

private final class RecordingImportClock: ImportClock, @unchecked Sendable {
    var current = Date(timeIntervalSince1970: 1_700_000_000)
    var sleeps: [Duration] = []

    var now: Date { current }

    func sleep(for duration: Duration) async throws {
        sleeps.append(duration)
        current.addTimeInterval(duration.secondsForTest)
    }
}

private struct CancellationProcessingClient: PatientAPIClient {
    private let documentID = UUID()

    func createImport(_ request: ImportRequest) async throws -> ImportTicket {
        ImportTicket(documentID: documentID, title: request.title)
    }

    func upload(_ request: UploadRequest) async throws -> UploadReceipt {
        UploadReceipt(ticketID: request.ticketID, documentID: documentID)
    }

    func processingStatus(documentID: UUID) async throws -> ProcessingStatus {
        throw CancellationError()
    }

    func facts(documentID: UUID) async throws -> [Fact] { [] }
    func editFact(_ command: FactEditCommand) async throws -> Fact { throw PatientAppError.factNotFound }
    func confirmFact(_ command: FactReviewCommand) async throws -> Fact { throw PatientAppError.factNotFound }
}

private extension Duration {
    var secondsForTest: TimeInterval {
        TimeInterval(components.seconds) + TimeInterval(components.attoseconds) / 1_000_000_000_000_000_000
    }
}
