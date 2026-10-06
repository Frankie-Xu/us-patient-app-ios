import XCTest
@testable import PatientAppDomain
@testable import PatientAppUI

@MainActor
final class UploadQueueImportMetadataTests: XCTestCase {
    func testImportedAssetMetadataIsAttachedWithoutChangingTransportPath() {
        let model = UploadQueueModel(client: DeterministicMockAPIClient())
        let bytes = Data([1, 2, 3])
        let metadata = ImportedAssetMetadata(
            fileName: "photo.jpg",
            title: "Photo",
            byteCount: bytes.count,
            mediaType: "image/jpeg",
            source: .photoLibrary,
            pageCount: 1,
            duplicateFingerprint: "fingerprint"
        )

        let id = model.enqueue(ImportedAsset(metadata: metadata, content: bytes))

        let item = model.items.first { $0.id == id }
        XCTAssertEqual(item?.metadata, metadata)
        XCTAssertEqual(item?.request.fileName, "photo.jpg")
        XCTAssertEqual(item?.request.content, bytes)
    }
}
