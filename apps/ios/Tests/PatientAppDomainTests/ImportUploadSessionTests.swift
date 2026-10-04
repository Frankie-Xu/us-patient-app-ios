
import Foundation
import XCTest
@testable import PatientAppDomain

final class ImportUploadSessionTests: XCTestCase {
    func testImportWithContentVerifiesUploadSessionBeforeProcessing() async throws {
        let content = Data("synthetic".utf8)
        let request = ImportRequest(
            fileName: "synthetic.txt",
            title: "Synthetic",
            byteCount: content.count,
            mediaType: "text/plain",
            sha256: String(repeating: "a", count: 64),
            content: content
        )

        let snapshot = try await ImportUseCase(client: DeterministicMockAPIClient()).run(request)
        XCTAssertEqual(snapshot.status, .ready)
    }

    func testImportRejectsMismatchedContentSizeBeforeUpload() async {
        let request = ImportRequest(
            fileName: "synthetic.txt",
            title: "Synthetic",
            byteCount: 10,
            mediaType: "text/plain",
            sha256: String(repeating: "a", count: 64),
            content: Data([1])
        )

        do {
            _ = try await ImportUseCase(client: DeterministicMockAPIClient()).run(request)
            XCTFail("Expected invalid input")
        } catch let error as PatientAppError {
            XCTAssertEqual(error, .invalidInput)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }
}
