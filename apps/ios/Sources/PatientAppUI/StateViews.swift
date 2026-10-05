import CryptoKit
import SwiftUI
import UniformTypeIdentifiers
import PatientAppDomain
#if canImport(PhotosUI)
import PhotosUI
#endif
#if canImport(UIKit)
import UIKit
#endif

struct HomeView: View {
    @ObservedObject var model: ImportFlowModel
    @ObservedObject private var observedQueue: OfflineUploadCoordinator
    let uploadQueue: OfflineUploadCoordinator?
    @State private var isFileImporterPresented = false
    @State private var isCameraPresented = false
    @State private var photoItem: PhotosPickerItem?
    @State private var fileError: String?

    init(model: ImportFlowModel, uploadQueue: OfflineUploadCoordinator? = nil) {
        self.model = model
        self.uploadQueue = uploadQueue
        _observedQueue = ObservedObject(wrappedValue: uploadQueue ?? OfflineUploadCoordinator(client: DeterministicMockAPIClient()))
    }
    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                Text("Record workspace").font(.title2)
                Text("Choose a local record or use fictional content for preview.")
                Button("Choose record file") {
                    isFileImporterPresented = true
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier(PatientAccessibilityIdentifier.homeImportFile)
                .disabled(model.isBusy)
#if canImport(PhotosUI)
                PhotosPicker(selection: $photoItem, matching: .images) {
                    Label("Import from Photos", systemImage: "photo")
                }
                .buttonStyle(.bordered)
                .disabled(model.isBusy)
                .accessibilityIdentifier(PatientAccessibilityIdentifier.homeImportPhotos)
#endif
#if canImport(UIKit)
                Button("Take a photo") {
                    isCameraPresented = true
                }
                .buttonStyle(.bordered)
                .disabled(model.isBusy)
                .accessibilityIdentifier(PatientAccessibilityIdentifier.homeImportCamera)
                .sheet(isPresented: $isCameraPresented) {
                    CameraCaptureView { imageData in
                        isCameraPresented = false
                        guard let imageData else { return }
                        _Concurrency.Task { await importImage(imageData) }
                    }
                }
#endif
                Button("Import synthetic record") {
                    let content = Data("synthetic fixture content".utf8)
                    _Concurrency.Task {
                        await importRequest(ImportRequest(fileName: "synthetic-record.txt", title: "Synthetic record", byteCount: content.count, mediaType: "text/plain", sha256: String(repeating: "0", count: 64), content: content))
                    }
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier(PatientAccessibilityIdentifier.homeImportSynthetic)
                .disabled(model.isBusy)
                if uploadQueue != nil {
                    Button("Queue for background upload") {
                        let content = Data("queued fixture content".utf8)
                        let request = ImportRequest(fileName: "queued-record.txt", title: "Queued synthetic record", byteCount: content.count, mediaType: "text/plain", sha256: String(repeating: "1", count: 64), content: content)
                        _ = observedQueue.enqueue(request)
                    }
                    .buttonStyle(.bordered)
                    Button("Process queued uploads") {
                        _Concurrency.Task { await observedQueue.start() }
                    }
                    .buttonStyle(.bordered)
                    Text("Queued items: \(observedQueue.items.count)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier(PatientAccessibilityIdentifier.homeUploadQueue)
                }
                if let fileError {
                    Text(fileError).foregroundStyle(.red)
                }
                FlowContent(model: model, allowsReview: false)
            }
            .padding()
            .navigationTitle("Home")
            .onChange(of: photoItem) { _, item in
                guard let item else { return }
                _Concurrency.Task { await importPhoto(item) }
            }
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
    private func importRequest(_ request: ImportRequest) async {
        if let uploadQueue { _ = uploadQueue.enqueue(request) }
        await model.start(request)
    }

#if canImport(PhotosUI)
    @MainActor
    private func importPhoto(_ item: PhotosPickerItem) async {
        defer { photoItem = nil }
        do {
            guard let data = try await item.loadTransferable(type: Data.self), !data.isEmpty else {
                fileError = "The selected photo is empty."
                return
            }
            await importImage(data)
        } catch {
            fileError = "The selected photo could not be read."
        }
    }
#endif

    @MainActor
    private func importImage(_ data: Data) async {
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        await importRequest(ImportRequest(fileName: "camera-record.jpg", title: "Camera record", byteCount: data.count, mediaType: "image/jpeg", sha256: digest, content: data))
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
            await importRequest(ImportRequest(
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
    let client: any PatientAPIClient
    let onReview: () -> Void

    init(model: ImportFlowModel, history: DocumentHistoryModel, client: any PatientAPIClient, onReview: @escaping () -> Void = {}) {
        self.model = model
        self.history = history
        self.client = client
        self.onReview = onReview
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    FlowContent(model: model, allowsReview: false)
                    Divider()
                    DocumentHistoryContent(history: history, importModel: model, client: client, onReview: onReview)
                }
                .padding()
            }
            .navigationTitle("Records")
            .refreshable { await history.load() }
            .task {
                if case .idle = history.state { await history.load() }
            }
            .onChange(of: model.state) { _, newState in
                switch newState {
                case .reviewRequired, .empty, .completed:
                    _Concurrency.Task { await history.load() }
                case .idle, .uploading, .processing, .failed:
                    break
                }
            }
        }
    }
}

private struct DocumentHistoryContent: View {
    @ObservedObject var history: DocumentHistoryModel
    @ObservedObject var importModel: ImportFlowModel
    let client: any PatientAPIClient
    let onReview: () -> Void

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
                    NavigationLink {
                        DocumentDetailView(document: document, client: client, importModel: importModel, onReview: onReview)
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(document.title).font(.body)
                            Text(document.processingStatus.displayName)
                                .font(.caption)
                                .foregroundStyle(document.processingStatus == .failed ? .red : .secondary)
                            Text("Version \(document.version) · Updated \(document.updatedAt, format: .dateTime.month().day().hour().minute())")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Label("Open record details", systemImage: "chevron.forward")
                                .font(.caption)
                                .foregroundStyle(.tint)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .accessibilityIdentifier("records.documentDetail.\(document.id.uuidString)")
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
            FlowContent(model: model, allowsReview: true)
                .safeAreaInset(edge: .bottom, spacing: 8) {
                    if model.currentSnapshot != nil {
                        VStack(spacing: 4) {
                            NavigationLink {
                                DoctorBriefView(model: model)
                            } label: {
                                Label("Prepare doctor visit", systemImage: "stethoscope")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(!model.canPrepareVisit)
                            .accessibilityIdentifier("review.prepareVisit")
                            if !model.canPrepareVisit {
                                Text("Confirm every traceable fact before preparing the visit.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.horizontal)
                        .padding(.top, 8)
                        .background(.bar)
                    }
                }
            .navigationTitle("Review")
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
                ProgressView("Uploading \\(model.currentImportTitle)…")
            case .processing:
                ProgressView("Processing \\(model.currentImportTitle)…")
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
            if let confidence = fact.confidence {
                Text("Confidence \(Int((confidence * 100).rounded()))%")
                    .font(.caption2)
                    .foregroundStyle(confidence < 0.8 ? .orange : .secondary)
                    .accessibilityLabel(Text("Confidence \(Int((confidence * 100).rounded())) percent"))
            } else {
                Text("Confidence unavailable")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
            if fact.reviewStatus != .confirmed {
                Label("Explicit review required before confirmation", systemImage: "exclamationmark.circle")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
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
        case .versionConflict, .validation, .shareExpired, .shareRevoked: "The records changed. Try again."
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
