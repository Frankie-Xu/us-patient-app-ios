import Foundation
import PatientAppDomain

public enum UploadQueueItemState: Equatable, Sendable {
    case queued
    case uploading
    case processing
    case ready
    case failed(PatientAppError)

    public var isRetryable: Bool {
        if case .failed = self { return true }
        return false
    }

    public var displayName: String {
        switch self {
        case .queued: "Waiting to upload"
        case .uploading: "Uploading"
        case .processing: "Processing"
        case .ready: "Ready for review"
        case .failed: "Upload failed"
        }
    }
}

public struct UploadQueueItem: Equatable, Identifiable, Sendable {
    public let id: UUID
    public let request: ImportRequest
    public var state: UploadQueueItemState
    public var progress: Double
    public var attempts: Int
    public var snapshot: ImportSnapshot?

    public init(id: UUID = UUID(), request: ImportRequest) {
        self.init(id: id, request: request, state: .queued, progress: 0, attempts: 0, snapshot: nil)
    }

    public init(
        id: UUID,
        request: ImportRequest,
        state: UploadQueueItemState,
        progress: Double,
        attempts: Int,
        snapshot: ImportSnapshot?
    ) {
        self.id = id
        self.request = request
        self.state = state
        self.progress = progress
        self.attempts = attempts
        self.snapshot = snapshot
    }
}

/// Coordinates multiple imports without changing the transport or upload-session
/// contract. Items are processed sequentially so memory pressure and server load
/// remain bounded; raw file bytes remain in the request only until completion.
@MainActor
public final class UploadQueueModel: ObservableObject {
    @Published public private(set) var items: [UploadQueueItem] = []
    @Published public private(set) var isRunning = false

    private let useCase: ImportUseCase

    public init(client: any PatientAPIClient) {
        self.useCase = ImportUseCase(client: client)
    }

    @discardableResult
    public func enqueue(_ request: ImportRequest) -> UUID {
        let item = UploadQueueItem(request: request)
        items.append(item)
        return item.id
    }

    /// Restores queue metadata from injected persistence. File bytes are omitted
    /// by design and can be reattached through OfflineUploadCoordinator.
    public func restore(_ restoredItems: [UploadQueueItem]) {
        guard !isRunning else { return }
        items = restoredItems
    }

    /// Reattaches file bytes after a persisted queue record is restored.
    public func attachContent(_ content: Data, for id: UUID) {
        guard let index = items.firstIndex(where: { $0.id == id }) else { return }
        let current = items[index]
        let request = ImportRequest(
            fileName: current.request.fileName,
            title: current.request.title,
            byteCount: current.request.byteCount,
            mediaType: current.request.mediaType,
            sha256: current.request.sha256,
            content: content
        )
        items[index] = UploadQueueItem(
            id: current.id,
            request: request,
            state: current.state,
            progress: current.progress,
            attempts: current.attempts,
            snapshot: current.snapshot
        )
    }

    public func start() async {
        guard !isRunning else { return }
        isRunning = true
        defer { isRunning = false }

        while let index = nextQueuedIndex {
            let item = items[index]
            markAttemptStarted(itemID: item.id)
            do {
                let snapshot = try await useCase.run(item.request) { [weak self] stage in
                    await self?.update(itemID: item.id, stage: stage)
                }
                guard let completedIndex = items.firstIndex(where: { $0.id == item.id }) else { continue }
                items[completedIndex].state = .ready
                items[completedIndex].progress = 1
                items[completedIndex].snapshot = snapshot
                clearPayload(itemID: item.id)
            } catch let error as PatientAppError {
                markFailed(itemID: item.id, error: error)
            } catch {
                markFailed(itemID: item.id, error: .unavailable)
            }
        }
    }

    public func retry(id: UUID) async {
        guard let index = items.firstIndex(where: { $0.id == id }), items[index].state.isRetryable else { return }
        items[index].state = .queued
        items[index].progress = 0
        items[index].snapshot = nil
        await start()
    }

    public func retryAllFailed() async {
        for index in items.indices where items[index].state.isRetryable {
            items[index].state = .queued
            items[index].progress = 0
            items[index].snapshot = nil
        }
        await start()
    }

    public var hasRetryableFailures: Bool {
        items.contains(where: { $0.state.isRetryable })
    }

    private var nextQueuedIndex: Int? {
        items.firstIndex(where: { if case .queued = $0.state { true } else { false } })
    }

    private func markAttemptStarted(itemID: UUID) {
        guard let index = items.firstIndex(where: { $0.id == itemID }) else { return }
        items[index].attempts += 1
        items[index].state = .uploading
        items[index].progress = 0.1
    }

    private func update(itemID: UUID, stage: ImportStage) {
        guard let index = items.firstIndex(where: { $0.id == itemID }) else { return }
        switch stage {
        case .uploading:
            items[index].state = .uploading
            items[index].progress = max(items[index].progress, 0.25)
        case .processing:
            items[index].state = .processing
            items[index].progress = max(items[index].progress, 0.65)
        case .loadingFacts:
            items[index].state = .processing
            items[index].progress = max(items[index].progress, 0.9)
        }
    }

    private func markFailed(itemID: UUID, error: PatientAppError) {
        guard let index = items.firstIndex(where: { $0.id == itemID }) else { return }
        items[index].state = .failed(error)
        items[index].progress = 0
    }

    private func clearPayload(itemID: UUID) {
        guard let index = items.firstIndex(where: { $0.id == itemID }) else { return }
        let current = items[index]
        guard current.request.content != nil else { return }
        let request = ImportRequest(
            fileName: current.request.fileName,
            title: current.request.title,
            byteCount: current.request.byteCount,
            mediaType: current.request.mediaType,
            sha256: current.request.sha256,
            content: nil
        )
        items[index] = UploadQueueItem(
            id: current.id,
            request: request,
            state: current.state,
            progress: current.progress,
            attempts: current.attempts,
            snapshot: current.snapshot
        )
    }
}
