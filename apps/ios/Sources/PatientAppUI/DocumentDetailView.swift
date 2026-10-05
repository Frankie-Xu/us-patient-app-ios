import SwiftUI
import PatientAppDomain

/// Presents the selected record, its current processing state, and version history.
/// Actions continue to use the injected client and import model so the mock and live
/// compositions share the same navigation path.
struct DocumentDetailView: View {
    let document: PatientAppDomain.Document
    let client: any PatientAPIClient
    @ObservedObject var importModel: ImportFlowModel
    let onReview: () -> Void
    @StateObject private var versionHistory: DocumentVersionHistoryModel

    init(
        document: PatientAppDomain.Document,
        client: any PatientAPIClient,
        importModel: ImportFlowModel,
        onReview: @escaping () -> Void
    ) {
        self.document = document
        self.client = client
        self.importModel = importModel
        self.onReview = onReview
        _versionHistory = StateObject(wrappedValue: DocumentVersionHistoryModel(client: client))
    }

    var body: some View {
        Form {
            Section("Record") {
                LabeledContent("Title", value: document.title)
                LabeledContent("Status", value: document.processingStatus.displayName)
                LabeledContent("Version", value: "(document.version)")
                LabeledContent("Updated", value: document.updatedAt.formatted(date: .abbreviated, time: .shortened))
                if let deletedAt = document.deletedAt {
                    LabeledContent("Deleted", value: deletedAt.formatted(date: .abbreviated, time: .shortened))
                }
            }

            Section("Actions") {
                Button {
                    _Concurrency.Task {
                        await importModel.loadExisting(document: document)
                        if case .reviewRequired = importModel.state {
                            onReview()
                        }
                    }
                } label: {
                    Label("Review facts and sources", systemImage: "checkmark.circle")
                }
                .disabled(importModel.isBusy || document.processingStatus != .ready)
                .accessibilityIdentifier("documentDetail.reviewFacts")

                NavigationLink {
                    DocumentVersionHistoryView(documentID: document.id, model: versionHistory)
                } label: {
                    Label("View version history", systemImage: "clock.arrow.circlepath")
                }
                .accessibilityIdentifier("documentDetail.versionHistory")
            }

            Section("Source") {
                Label("Original file retained in the protected record store.", systemImage: "lock.shield")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Text("Source spans and extracted facts are shown during review. Confirmed facts can continue to the doctor brief.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Record details")
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
