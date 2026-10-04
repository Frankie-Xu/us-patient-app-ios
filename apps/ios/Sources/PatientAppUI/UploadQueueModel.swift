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
        self.id = id
        self.request = request
        self.state = .queued
        self.progress = 0
        self.attempts = 0
        self.snapshot = nil
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
}
