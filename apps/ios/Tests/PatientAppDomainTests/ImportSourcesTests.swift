import XCTest
@testable import PatientAppDomain

final class ImportSourcesTests: XCTestCase {
    func testPDFProviderPreservesPageCountAndBridgesToImportRequest() async throws {
        let content = Data([0x25, 0x50, 0x44, 0x46])
        let metadata = ImportedAssetMetadata(
            fileName: "scan.pdf",
            title: "Lab scan",
            byteCount: content.count,
            mediaType: "application/pdf",
            source: .pdf,
            pageCount: 4,
            fileUTI: "com.adobe.pdf",
            duplicateFingerprint: "sha256:test"
        )
        let provider = ImportAssetProviders.pdf {
            ImportedAsset(metadata: metadata, content: content)
        }

        let asset = try await provider.load()

        XCTAssertEqual(asset.metadata.pageCount, 4)
        XCTAssertEqual(asset.metadata.source, .pdf)
        XCTAssertEqual(asset.request().title, "Lab scan")
        XCTAssertEqual(asset.request().byteCount, content.count)
        XCTAssertEqual(asset.request().content, content)
    }

    func testProviderRejectsMismatchedSourceOrByteCount() async throws {
        let metadata = ImportedAssetMetadata(fileName: "photo.jpg", byteCount: 3, mediaType: "image/jpeg", source: .camera)
        let provider = ImportAssetProviders.files {
            ImportedAsset(metadata: metadata, content: Data([1, 2, 3]))
        }

        do {
            _ = try await provider.load()
            XCTFail("A provider must reject an asset tagged for another source")
        } catch let error as PatientAppError {
            XCTAssertEqual(error, .invalidInput)
        }
    }
}
