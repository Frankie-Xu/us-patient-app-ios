import Foundation

/// The user-visible origin of an imported medical record.
public enum ImportSourceKind: String, Codable, CaseIterable, Sendable {
    case files
    case camera
    case photoLibrary = "photo_library"
    case pdf
}

/// Metadata collected at the platform boundary. It is safe to persist with an
/// upload queue item; the bytes themselves remain transient and are never
/// encoded into queue metadata.
public struct ImportedAssetMetadata: Codable, Equatable, Hashable, Sendable {
    public let fileName: String
    public let title: String
    public let byteCount: Int
    public let mediaType: String
    public let source: ImportSourceKind
    public let pageCount: Int
    public let capturedAt: Date?
    public let fileUTI: String?
    public let duplicateFingerprint: String?

    public init(
        fileName: String,
        title: String? = nil,
        byteCount: Int,
        mediaType: String,
        source: ImportSourceKind,
        pageCount: Int = 1,
        capturedAt: Date? = nil,
        fileUTI: String? = nil,
        duplicateFingerprint: String? = nil
    ) {
        self.fileName = fileName
        self.title = title ?? fileName
        self.byteCount = max(0, byteCount)
        self.mediaType = mediaType
        self.source = source
        self.pageCount = max(1, pageCount)
        self.capturedAt = capturedAt
        self.fileUTI = fileUTI
        self.duplicateFingerprint = duplicateFingerprint
    }
}

public struct ImportedAsset: Equatable, Hashable, Sendable {
    public let metadata: ImportedAssetMetadata
    public let content: Data

    public init(metadata: ImportedAssetMetadata, content: Data) {
        self.metadata = metadata
        self.content = content
    }

    public func request(title: String? = nil) -> ImportRequest {
        ImportRequest(
            fileName: metadata.fileName,
            title: title ?? metadata.title,
            byteCount: content.count,
            mediaType: metadata.mediaType,
            sha256: metadata.duplicateFingerprint,
            content: content
        )
    }
}

/// A platform-neutral seam for Files, camera, photo-library, and PDF adapters.
/// UIKit, Photos, and PDFKit implementations can be injected by the app target
/// without changing the upload queue or transport contract.
public protocol ImportAssetProvider: Sendable {
    var source: ImportSourceKind { get }
    func load() async throws -> ImportedAsset
}

public struct ClosureImportAssetProvider: ImportAssetProvider {
    public let source: ImportSourceKind
    private let loader: @Sendable () async throws -> ImportedAsset

    public init(source: ImportSourceKind, loader: @escaping @Sendable () async throws -> ImportedAsset) {
        self.source = source
        self.loader = loader
    }

    public func load() async throws -> ImportedAsset {
        let asset = try await loader()
        guard asset.metadata.source == source else {
            throw PatientAppError.invalidInput
        }
        guard !asset.content.isEmpty, asset.metadata.byteCount == asset.content.count else {
            throw PatientAppError.invalidInput
        }
        return asset
    }
}

public enum ImportAssetProviders {
    public static func files(loader: @escaping @Sendable () async throws -> ImportedAsset) -> ClosureImportAssetProvider {
        ClosureImportAssetProvider(source: .files, loader: loader)
    }

    public static func camera(loader: @escaping @Sendable () async throws -> ImportedAsset) -> ClosureImportAssetProvider {
        ClosureImportAssetProvider(source: .camera, loader: loader)
    }

    public static func photoLibrary(loader: @escaping @Sendable () async throws -> ImportedAsset) -> ClosureImportAssetProvider {
        ClosureImportAssetProvider(source: .photoLibrary, loader: loader)
    }

    public static func pdf(loader: @escaping @Sendable () async throws -> ImportedAsset) -> ClosureImportAssetProvider {
        ClosureImportAssetProvider(source: .pdf, loader: loader)
    }
}
