import Foundation
import XCTest
@testable import PatientAppDomain

final class ShareExportTests: XCTestCase {
    func testDeterministicClientReportsActiveShareAndPDFArtifact() async throws {
        let client = DeterministicMockAPIClient()
        let creation = try await client.createShare(
            ShareCreateRequest(
                resourceType: .document,
                resourceID: UUID(),
                resourceVersion: 2,
                expiresAt: Date(timeIntervalSince1970: 4_000_000_000)
            )
        )

        let status = try await ShareUseCase(client: client).status(id: creation.share.id)
        XCTAssertEqual(status.state, .active)
        XCTAssertTrue(status.isAccessible)

        let artifact = try await PDFExportUseCase(client: client).export(
            documentID: creation.share.resourceID,
            documentVersion: 2
        )
        XCTAssertEqual(artifact.contentType, "application/pdf")
        XCTAssertEqual(artifact.documentVersion, 2)
        XCTAssertEqual(artifact.data, Data("%PDF-1.4\nsynthetic export\n".utf8))
        XCTAssertEqual(artifact.sha256.count, 64)
    }

    func testContractShareStatusPreservesExpiredAndRevokedStates() throws {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let base = ContractShareVersionPayload(
            id: UUID(),
            ownerID: "patient-1",
            resourceType: .document,
            resourceID: UUID(),
            resourceVersion: 4,
            expiresAt: now,
            status: .expired,
            revokedAt: nil,
            createdAt: now.addingTimeInterval(-60)
        )
        let expired = try base.accessStatus()
        XCTAssertEqual(expired.state, .expired)
        XCTAssertEqual(expired.share.state, .shared)
        XCTAssertFalse(expired.isAccessible)

        let revokedPayload = ContractShareVersionPayload(
            id: base.id,
            ownerID: base.ownerID,
            resourceType: base.resourceType,
            resourceID: base.resourceID,
            resourceVersion: base.resourceVersion,
            expiresAt: base.expiresAt,
            status: .revoked,
            revokedAt: now,
            createdAt: base.createdAt
        )
        let revoked = try revokedPayload.accessStatus()
        XCTAssertEqual(revoked.state, .revoked)
        XCTAssertEqual(revoked.share.state, .revoked)
        XCTAssertFalse(revoked.isAccessible)
    }

    func testURLSessionClientUsesStatusAndPDFEndpoints() async throws {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let shareID = UUID()
        let documentID = UUID()
        let payload = ContractShareVersionPayload(
            id: shareID,
            ownerID: "patient-1",
            resourceType: .document,
            resourceID: documentID,
            resourceVersion: 3,
            expiresAt: now.addingTimeInterval(3_600),
            status: .active,
            revokedAt: nil,
            createdAt: now
        )
        let transport = ShareExportScriptedTransport { request in
            switch request.path {
            case "/v1/shares/\(shareID.uuidString)":
                return try encodedShareResponse(payload)
            case "/v1/documents/\(documentID.uuidString)/exports/pdf":
                return PatientAPITransportResponse(
                    statusCode: 200,
                    headers: [
                        "content-type": "application/pdf",
                        "x-document-version": "3",
                        "x-content-sha256": String(repeating: "b", count: 64)
                    ],
                    body: Data("%PDF-1.4\nserver export\n".utf8)
                )
            default:
                return PatientAPITransportResponse(statusCode: 404)
            }
        }
        let client = URLSessionPatientAPIClient(transport: transport)

        let status = try await client.shareStatus(id: shareID)
        XCTAssertEqual(status.state, .active)
        let artifact = try await client.exportPDF(documentID: documentID, documentVersion: 3)
        XCTAssertEqual(artifact.data, Data("%PDF-1.4\nserver export\n".utf8))
        XCTAssertEqual(artifact.contentType, "application/pdf")
        XCTAssertEqual(artifact.documentVersion, 3)
        XCTAssertEqual(artifact.sha256, String(repeating: "b", count: 64))

        let requests = await transport.requests()
        XCTAssertEqual(requests.map(\.path), [
            "/v1/shares/\(shareID.uuidString)",
            "/v1/documents/\(documentID.uuidString)/exports/pdf"
        ])
        let body = try XCTUnwrap(requests.last?.body)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertEqual(json["document_version"] as? Int, 3)
        XCTAssertEqual(requests.last?.headers["Content-Type"], "application/json")
    }

    func testURLSessionClientMapsRevokedAndVersionConflictErrors() async throws {
        let shareID = UUID()
        let documentID = UUID()
        let transport = ShareExportScriptedTransport { request in
            if request.path.contains("/v1/shares/") {
                return PatientAPITransportResponse(
                    statusCode: 410,
                    body: Data(#"{ "code": "SHARE_REVOKED" }"#.utf8)
                )
            }
            return PatientAPITransportResponse(statusCode: 409, body: Data(#"{ "code": "VERSION_CONFLICT" }"#.utf8))
        }
        let client = URLSessionPatientAPIClient(transport: transport)

        do {
            _ = try await client.shareStatus(id: shareID)
            XCTFail("revoked share must map to a stable error")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .shareRevoked)
        }

        do {
            _ = try await client.exportPDF(documentID: documentID, documentVersion: 1)
            XCTFail("version mismatch must map to a stable error")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .versionConflict)
        }
    }

    func testPDFExportRejectsMissingResponseMetadata() async throws {
        let transport = ShareExportScriptedTransport { _ in
            PatientAPITransportResponse(statusCode: 200, body: Data("%PDF-1.4".utf8))
        }
        let client = URLSessionPatientAPIClient(transport: transport)

        do {
            _ = try await client.exportPDF(documentID: UUID(), documentVersion: 1)
            XCTFail("missing metadata must not produce an unverifiable artifact")
        } catch let error as PatientAPIClientError {
            XCTAssertEqual(error, .decoding)
        }
    }
}

private func encodedShareResponse(_ payload: ContractShareVersionPayload) throws -> PatientAPITransportResponse {
    let encoder = JSONEncoder()
    encoder.dateEncodingStrategy = .iso8601
    return PatientAPITransportResponse(statusCode: 200, body: try encoder.encode(payload))
}

private actor ShareExportScriptedTransport: PatientAPITransport {
    private var recorded: [PatientAPITransportRequest] = []
    private let responder: @Sendable (PatientAPITransportRequest) throws -> PatientAPITransportResponse

    init(responder: @escaping @Sendable (PatientAPITransportRequest) throws -> PatientAPITransportResponse) {
        self.responder = responder
    }

    func send(_ request: PatientAPITransportRequest) async throws -> PatientAPITransportResponse {
        recorded.append(request)
        return try responder(request)
    }

    func requests() -> [PatientAPITransportRequest] { recorded }
}
