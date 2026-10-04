import Foundation
import PatientAppDomain

public enum PersistedUploadQueueStatus: String, Codable, Sendable {
    case queued
    case uploading
    case processing
    case ready
    case failed
}

/// Queue metadata persisted across launches. Raw file bytes are never encoded;
/// the caller can attach bytes again with OfflineUploadCoordinator.attachPayload.
public struct PersistedUploadQueueItem: Codable, Equatable, Sendable, Identifiable {
    public let id: UUID
    public let fileName: String
    public let title: String
    public let byteCount: Int
    public let mediaType: String?
    public let sha256: String?
    public let status: PersistedUploadQueueStatus
    public let progress: Double
    public let attempts: Int
    public let snapshot: ImportSnapshot?
    public let failureCode: String?
    public let updatedAt: Date

    public init(item: UploadQueueItem, now: Date) {
        id = item.id
        fileName = item.request.fileName
        title = item.request.title
        byteCount = item.request.byteCount
        mediaType = item.request.mediaType
        sha256 = item.request.sha256
        progress = item.progress
        attempts = item.attempts
        snapshot = item.snapshot
        updatedAt = now

        switch item.state {
        case .queued:
            status = .queued
            failureCode = nil
        case .uploading:
            status = .uploading
            failureCode = nil
        case .processing:
            status = .processing
            failureCode = nil
        case .ready:
            status = .ready
            failureCode = nil
        case let .failed(error):
            status = .failed
            failureCode = Self.failureCode(for: error)
        }
    }

    public func restoreItem() -> UploadQueueItem {
        let request = ImportRequest(
            fileName: fileName,
            title: title,
            byteCount: byteCount,
            mediaType: mediaType,
            sha256: sha256,
            content: nil
        )
        let state: UploadQueueItemState
        switch status {
        case .queued: state = .queued
        case .uploading: state = .queued
        case .processing: state = .queued
        case .ready: state = .ready
        case .failed: state = .failed(Self.error(for: failureCode))
        }
        return UploadQueueItem(
            id: id,
            request: request,
            state: state,
            progress: progress,
            attempts: attempts,
            snapshot: snapshot
        )
    }

    private static func failureCode(for error: PatientAppError) -> String {
        switch error {
        case .unavailable: "unavailable"
        case .invalidInput: "invalid_input"
        case .uploadFailed: "upload_failed"
        case .processingFailed: "processing_failed"
        case .processingTimeout: "processing_timeout"
        case .processingCancelled: "processing_cancelled"
        case .factNotFound: "fact_not_found"
        case .versionConflict: "version_conflict"
        case .invalidTransition: "invalid_transition"
        case .reviewRequired: "review_required"
        case .sourceRequired: "source_required"
        case .invalidContractData: "invalid_contract_data"
        }
    }

    private static func error(for code: String?) -> PatientAppError {
        switch code {
        case "invalid_input": .invalidInput
        case "upload_failed": .uploadFailed
        case "processing_failed": .processingFailed
        case "processing_timeout": .processingTimeout
        case "processing_cancelled": .processingCancelled
        case "fact_not_found": .factNotFound
        case "version_conflict": .versionConflict
        case "review_required": .reviewRequired
        case "source_required": .sourceRequired
        case "invalid_contract_data": .invalidContractData(.unsupportedResourceType)
        default: .unavailable
        }
    }
}

public protocol UploadQueuePersistence: Sendable {
    func load() async throws -> [PersistedUploadQueueItem]
    func save(_ items: [PersistedUploadQueueItem]) async throws
}

public actor InMemoryUploadQueuePersistence: UploadQueuePersistence {
    private var records: [PersistedUploadQueueItem] = []

    public init() {}

    public func load() async throws -> [PersistedUploadQueueItem] {
        records
    }

    public func save(_ items: [PersistedUploadQueueItem]) async throws {
        records = items
    }
}

public protocol UploadBackgroundScheduler: Sendable {
    func schedule(identifier: String) async
}

public struct NoopUploadBackgroundScheduler: UploadBackgroundScheduler, Sendable {
    public init() {}
    public func schedule(identifier: String) async {}
}

public enum UploadQueueNotification: Equatable, Sendable {
    case queued(UUID, String)
    case completed(UUID, String)
    case failed(UUID, String, String)
    case wentOffline
    case networkRecovered
    case backgroundUploadScheduled
}

public protocol UploadQueueNotificationSink: Sendable {
    func publish(_ notification: UploadQueueNotification) async
}

public struct NoopUploadQueueNotificationSink: UploadQueueNotificationSink, Sendable {
    public init() {}
    public func publish(_ notification: UploadQueueNotification) async {}
}

/// Adds offline persistence, recovery and background scheduling around the
/// existing UploadQueueModel without changing the API transport contract.
@MainActor
public final class OfflineUploadCoordinator: ObservableObject {
    public static let backgroundTaskIdentifier = "patient-app.uploads"

    @Published public private(set) var items: [UploadQueueItem] = []
    @Published public private(set) var isOnline: Bool
    @Published public private(set) var isRestoring = false
    @Published public private(set) var lastPersistenceFailure: String?

    private let queue: UploadQueueModel
    private let persistence: any UploadQueuePersistence
    private let clock: any ImportClock
    private let scheduler: any UploadBackgroundScheduler
    private let notifications: any UploadQueueNotificationSink
    private let maxAttempts: Int

    public init(
        client: any PatientAPIClient,
        persistence: any UploadQueuePersistence = InMemoryUploadQueuePersistence(),
        clock: any ImportClock = SystemImportClock(),
        scheduler: any UploadBackgroundScheduler = NoopUploadBackgroundScheduler(),
        notifications: any UploadQueueNotificationSink = NoopUploadQueueNotificationSink(),
        isOnline: Bool = true,
        maxAttempts: Int = 3
    ) {
        queue = UploadQueueModel(client: client)
        self.persistence = persistence
        self.clock = clock
        self.scheduler = scheduler
        self.notifications = notifications
        self.isOnline = isOnline
        self.maxAttempts = max(1, maxAttempts)
    }

    @discardableResult
    public func enqueue(_ request: ImportRequest) -> UUID {
        if let existing = items.first(where: { Self.fingerprint($0.request) == Self.fingerprint(request) }) {
            return existing.id
        }
        let id = queue.enqueue(request)
        syncItems()
        return id
    }

    public func restore() async {
        guard !isRestoring else { return }
        isRestoring = true
        defer { isRestoring = false }
        do {
            let records = try await persistence.load()
            queue.restore(records.map { $0.restoreItem() })
            syncItems()
            lastPersistenceFailure = nil
        } catch {
            lastPersistenceFailure = String(describing: error)
        }
    }

    /// Persists state and metadata only; upload bytes remain in memory.
    public func persist() async {
        do {
            let records = items.map { PersistedUploadQueueItem(item: $0, now: clock.now) }
            try await persistence.save(records)
            lastPersistenceFailure = nil
        } catch {
            lastPersistenceFailure = String(describing: error)
        }
    }

    public func attachPayload(_ content: Data, for id: UUID) {
        queue.attachContent(content, for: id)
        syncItems()
    }

    public func start() async {
        guard isOnline else {
            await notifications.publish(.wentOffline)
            return
        }
        let before = items
        await queue.start()
        syncItems()
        await notifyTransitions(from: before, to: items)
        await persist()
    }

    public func setOnline(_ online: Bool) async {
        guard online != isOnline else { return }
        isOnline = online
        if online {
            await notifications.publish(.networkRecovered)
            await scheduleBackgroundUpload()
            await retryPending()
        } else {
            await notifications.publish(.wentOffline)
        }
    }

    public func retry(id: UUID) async {
        guard let item = items.first(where: { $0.id == id }), item.state.isRetryable, item.attempts < maxAttempts else {
            return
        }
        let before = items
        await queue.retry(id: id)
        syncItems()
        await notifyTransitions(from: before, to: items)
        await persist()
    }

    public func retryAllFailed() async {
        let retryableIDs = items
            .filter { $0.state.isRetryable && $0.attempts < maxAttempts }
            .map(\.id)
        for id in retryableIDs {
            await retry(id: id)
        }
    }

    public func scheduleBackgroundUpload() async {
        guard items.contains(where: Self.isPending) else { return }
        await scheduler.schedule(identifier: Self.backgroundTaskIdentifier)
        await notifications.publish(.backgroundUploadScheduled)
    }

    private func retryPending() async {
        let retryableIDs = items
            .filter { $0.state.isRetryable && $0.attempts < maxAttempts }
            .map(\.id)
        for id in retryableIDs {
            await retry(id: id)
        }
        if items.contains(where: { if case .queued = $0.state { true } else { false } }) {
            await start()
        }
    }

    private func notifyTransitions(from before: [UploadQueueItem], to after: [UploadQueueItem]) async {
        let previous = Dictionary(uniqueKeysWithValues: before.map { ($0.id, $0) })
        for item in after {
            let old = previous[item.id]?.state
            switch item.state {
            case .ready where old != .ready:
                await notifications.publish(.completed(item.id, item.request.title))
            case let .failed(error) where old != item.state:
                await notifications.publish(.failed(item.id, item.request.title, Self.errorCode(error)))
            default:
                break
            }
        }
    }

    private func syncItems() {
        items = queue.items
    }

    private static func isPending(_ item: UploadQueueItem) -> Bool {
        switch item.state {
        case .queued, .uploading, .processing: true
        case .ready, .failed: false
        }
    }

    private static func fingerprint(_ request: ImportRequest) -> String {
        [
            request.fileName,
            request.title,
            String(request.byteCount),
            request.mediaType ?? "",
            request.sha256 ?? ""
        ].joined(separator: "\u{1F}")
    }

    private static func errorCode(_ error: PatientAppError) -> String {
        switch error {
        case .unavailable: "unavailable"
        case .invalidInput: "invalid_input"
        case .uploadFailed: "upload_failed"
        case .processingFailed: "processing_failed"
        case .processingTimeout: "processing_timeout"
        case .processingCancelled: "processing_cancelled"
        case .factNotFound: "fact_not_found"
        case .versionConflict: "version_conflict"
        case .invalidTransition: "invalid_transition"
        case .reviewRequired: "review_required"
        case .sourceRequired: "source_required"
        case .invalidContractData: "invalid_contract_data"
        }
    }
}
