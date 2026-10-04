import XCTest
@testable import PatientAppDomain

final class ShareUseCaseTests: XCTestCase {
    func testCreateVisitShareReturnsVersionPinnedSyntheticToken() async throws {
        let visitID = UUID()
        let now = Date(timeIntervalSince1970: 1_000)
        let client = DeterministicMockAPIClient()
        let useCase = ShareUseCase(client: client)
        let request = ShareCreateRequest(
            resourceType: .visit,
            resourceID: visitID,
            resourceVersion: 3,
            expiresAt: now.addingTimeInterval(3_600),
            idempotencyKey: "share-test"
        )

        let creation = try await useCase.create(request, now: { now })

        XCTAssertEqual(creation.share.resourceType, .visit)
        XCTAssertEqual(creation.share.resourceID, visitID)
        XCTAssertEqual(creation.share.version, 3)
        XCTAssertTrue(creation.token.hasPrefix("synthetic-share-"))
    }

    func testCreateRejectsInvalidVersionAndExpiredRequestBeforeTransport() async {
        let now = Date(timeIntervalSince1970: 1_000)
        let useCase = ShareUseCase(client: DeterministicMockAPIClient())

        do {
            _ = try await useCase.create(
                ShareCreateRequest(resourceType: .visit, resourceID: UUID(), resourceVersion: 0, expiresAt: now.addingTimeInterval(100)),
                now: { now }
            )
            XCTFail("Expected invalid version")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .invalidRequest)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        do {
            _ = try await useCase.create(
                ShareCreateRequest(resourceType: .visit, resourceID: UUID(), resourceVersion: 1, expiresAt: now),
                now: { now }
            )
            XCTFail("Expected expired request")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .invalidRequest)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testRevokeMarksShareRevoked() async throws {
        let client = DeterministicMockAPIClient()
        let useCase = ShareUseCase(client: client)
        let creation = try await useCase.create(
            ShareCreateRequest(
                resourceType: .visit,
                resourceID: UUID(),
                resourceVersion: 1,
                expiresAt: Date().addingTimeInterval(3_600)
            )
        )

        let revoked = try await useCase.revoke(id: creation.share.id)

        XCTAssertEqual(revoked.state, .revoked)
        XCTAssertNotNil(revoked.revokedAt)
    }
}
