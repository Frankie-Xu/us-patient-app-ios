import CryptoKit
import SwiftUI
import UniformTypeIdentifiers
import PatientAppDomain

struct HomeView: View {
    @ObservedObject var model: ImportFlowModel
    @State private var isFileImporterPresented = false
    @State private var fileError: String?
    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                Text("Synthetic record workspace").font(.title2)
                Text("Choose a local record or use fictional content for preview.")
                Button("Choose record file") {
                    isFileImporterPresented = true
                }
                .buttonStyle(.bordered)
                .disabled(model.isBusy)
                Button("Import synthetic record") {
                    _Concurrency.Task {
                        await model.start(ImportRequest(fileName: "synthetic-record.txt", title: "Synthetic record"))
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.isBusy)
                if let fileError {
                    Text(fileError).foregroundStyle(.red)
                }
                FlowContent(model: model, allowsReview: false)
            }
            .padding()
            .navigationTitle("Home")
            .fileImporter(
                isPresented: $isFileImporterPresented,
                allowedContentTypes: [.pdf, .plainText, .data],
                allowsMultipleSelection: false
            ) { result in
                switch result {
                case let .success(urls):
                    guard let url = urls.first else { return }
                    _Concurrency.Task { await importFile(at: url) }
                case .failure:
                    fileError = "The file could not be selected."
                }
            }
        }
    }

    @MainActor
    private func importFile(at url: URL) async {
        let hasAccess = url.startAccessingSecurityScopedResource()
        defer {
            if hasAccess { url.stopAccessingSecurityScopedResource() }
        }
        do {
            let data = try Data(contentsOf: url, options: [.mappedIfSafe])
            guard !data.isEmpty, data.count <= 10 * 1024 * 1024 else {
                fileError = "Choose a file between 1 byte and 10 MiB."
                return
            }
            let values = try url.resourceValues(forKeys: [.contentTypeKey])
            let mediaType = values.contentType?.preferredMIMEType ?? "application/octet-stream"
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            fileError = nil
            await model.start(
                ImportRequest(
                    fileName: url.lastPathComponent,
                    title: url.deletingPathExtension().lastPathComponent,
                    byteCount: data.count,
                    mediaType: mediaType,
                    sha256: digest,
                    content: data
                )
            )
        } catch {
            fileError = "The file could not be read. Choose another file."
        }
    }
}

struct RecordsView: View {
    @ObservedObject var model: ImportFlowModel
    @ObservedObject var history: DocumentHistoryModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    FlowContent(model: model, allowsReview: false)
                    Divider()
                    DocumentHistoryContent(history: history)
                }
                .padding()
            }
            .navigationTitle("Records")
            .refreshable { await history.load() }
            .task {
                if case .idle = history.state { await history.load() }
            }
        }
    }
}

private struct DocumentHistoryContent: View {
    @ObservedObject var history: DocumentHistoryModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Imported records").font(.headline)
            switch history.state {
            case .idle, .loading:
                ProgressView("Loading records…")
            case .empty:
                ContentUnavailableView("No imported records", systemImage: "doc.text", description: Text("Choose a record file on Home to get started."))
            case let .loaded(documents):
                ForEach(documents) { document in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(document.title).font(.body)
                        Text(document.processingStatus.displayName)
                            .font(.caption)
                            .foregroundStyle(document.processingStatus == .failed ? .red : .secondary)
                        Text("Version \(document.version) · Updated \(document.updatedAt, format: .dateTime.month().day().hour().minute())")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 4)
                }
            case let .failed(error):
                Text(error.displayMessage).foregroundStyle(.red)
                Button("Try again") { _Concurrency.Task { await history.retry() } }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ReviewView: View {
    @ObservedObject var model: ImportFlowModel
    var body: some View {
        NavigationStack {
            FlowContent(model: model, allowsReview: true).navigationTitle("Review")
        }
    }
}

private struct FlowContent: View {
    @ObservedObject var model: ImportFlowModel
    let allowsReview: Bool
    var body: some View {
        VStack {
            if let error = model.error {
                Text(error.displayMessage).foregroundStyle(.red)
                Button("Try again") { _Concurrency.Task { await model.retry() } }
                    .disabled(model.isBusy)
            }
            switch model.state {
            case .idle:
                ContentUnavailableView("No records", systemImage: "tray", description: Text("Start a synthetic import from Home."))
            case .uploading:
                ProgressView("Uploading synthetic record…")
            case .processing:
                ProgressView("Processing synthetic record…")
            case let .reviewRequired(snapshot), let .completed(snapshot):
                Text(snapshot.ticket.title).font(.headline)
                if allowsReview {
                    List(snapshot.facts) { fact in
                        FactReviewRow(fact: fact, busy: model.isBusy) { value in
                            _Concurrency.Task { await model.editFact(fact, value: value) }
                        } confirm: {
                            _Concurrency.Task { await model.confirmFact(fact) }
                        }
                    }
                } else {
                    Text("\(snapshot.facts.count) facts available in Review.")
                }
            case .empty:
                ContentUnavailableView("No facts found", systemImage: "tray", description: Text("Processing completed without reviewable facts."))
            case .failed:
                ContentUnavailableView("Import paused", systemImage: "exclamationmark.triangle", description: Text("Use Try again to resume the failed step."))
            }
            if model.isBusy { ProgressView() }
        }
    }
}

private struct FactReviewRow: View {
    let fact: Fact
    let busy: Bool
    let edit: (String) -> Void
    let confirm: () -> Void
    @State private var value: String

    init(fact: Fact, busy: Bool, edit: @escaping (String) -> Void, confirm: @escaping () -> Void) {
        self.fact = fact
        self.busy = busy
        self.edit = edit
        self.confirm = confirm
        _value = State(initialValue: fact.value)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(fact.state.displayName).font(.caption)
            TextField("Fact", text: $value)
            if let source = fact.sourceReference {
                Text("Source document: \(source.documentID.uuidString)")
                Text("Location: \(source.locator)")
            } else {
                Text(fact.isUserInput ? "Patient-entered value" : "Source required before confirmation")
            }
            HStack {
                Button("Save edit") { edit(value) }
                    .disabled(busy || value == fact.value || value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("Confirm reviewed fact", action: confirm)
                    .disabled(busy || value != fact.value || fact.state != .needsReview || !fact.isTraceable)
            }
            .buttonStyle(.bordered)
            if value != fact.value { Text("Save your edit before confirming.").font(.caption) }
        }
        .onChange(of: fact.value) { _, newValue in value = newValue }
        .padding(.vertical, 6)
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

private extension PatientAPIClientError {
    var displayMessage: String {
        switch self {
        case .unauthorized, .missingBearerToken: "Sign in to view imported records."
        case .forbidden: "You do not have access to these records."
        case .notFound: "The records are unavailable."
        case .server: "The service could not load records. Try again."
        case .transport: "The records could not be loaded. Try again."
        case .decoding, .invalidRequest, .invalidBaseURL, .unsupported: "The service returned an unsupported record list."
        case .versionConflict, .validation: "The records changed. Try again."
        }
    }
}

private extension PatientAppError {
    var displayMessage: String {
        switch self {
        case .invalidInput: "Enter a nonempty value."
        case .sourceRequired: "A source or explicit patient input is required."
        case .reviewRequired: "Review is required."
        case .factNotFound: "The fact is no longer available."
        case .uploadFailed: "The upload failed. Try again."
        case .processingFailed: "Processing did not complete. Try again."
        case .processingTimeout: "Processing took too long. Try again."
        case .processingCancelled: "Processing was cancelled."
        case .versionConflict: "This record changed. Reload it before reviewing."
        case .invalidContractData: "The service returned an unsupported record."
        case .invalidTransition: "This action is unavailable in the current state."
        case .unavailable: "The operation is temporarily unavailable."
        }
    }
}
