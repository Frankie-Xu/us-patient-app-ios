import SwiftUI
import PatientAppDomain

/// Reusable version-history surface for Records and document detail flows.
public struct DocumentVersionHistoryView: View {
    @ObservedObject private var model: DocumentVersionHistoryModel
    private let documentID: UUID

    public init(documentID: UUID, model: DocumentVersionHistoryModel) {
        self.documentID = documentID
        self.model = model
    }

    public var body: some View {
        Group {
            switch model.state {
            case .idle:
                ContentUnavailableView("No version history", systemImage: "clock.arrow.circlepath")
            case .loading:
                ProgressView("Loading versions…")
            case .empty:
                ContentUnavailableView("No prior versions", systemImage: "doc.text")
            case let .loaded(versions):
                List(versions) { version in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text("Version \(version.version)")
                                .font(.headline)
                            if version.version == versions.map(\.version).max() {
                                Text("Current")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.tint)
                                    .accessibilityLabel("Current version")
                            }
                        }
                        Text(version.title)
                        Text(version.processingStatus.displayName)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(version.updatedAt, format: .dateTime.month().day().year().hour().minute())
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel(
                        "Version \(version.version), \(version.version == versions.map(\.version).max() ? "current, " : "")\(version.processingStatus.displayName), \(version.title)"
                    )
                    .accessibilityIdentifier("document.versionHistory.row.\(version.version)")
                }
                .refreshable {
                    await model.load(documentID: documentID)
                }
            case let .failed(error):
                VStack(spacing: 12) {
                    Text("Version history could not be loaded.")
                        .foregroundStyle(.red)
                        .accessibilityIdentifier("document.versionHistory.error")
                    Button("Try again") {
                        _Concurrency.Task { await model.retry() }
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("document.versionHistory.retry")
                    Text(String(describing: error))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .task(id: documentID) {
            if case .idle = model.state {
                await model.load(documentID: documentID)
            }
        }
    }
}

private extension DocumentProcessingStatus {
    var displayName: String {
        switch self {
        case .uploaded: "Uploaded"
        case .processing: "Processing"
        case .ready: "Ready"
        case .failed: "Processing failed"
        case .deleted: "Deleted"
        }
    }
}
