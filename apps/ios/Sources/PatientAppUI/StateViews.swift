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
            .accessibilityIdentifier(PatientAccessibilityIdentifier.tabHome)
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
            .accessibilityIdentifier(PatientAccessibilityIdentifier.tabRecords)
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
                                ReviewContinuePrompt(facts: model.currentSnapshot?.facts ?? [])
                            }
                        }
                        .padding(.horizontal)
                        .padding(.top, 8)
                        .background(.bar)
                    }
                }
            .navigationTitle("Review")
            .accessibilityIdentifier(PatientAccessibilityIdentifier.tabReview)
        }
    }
}

private struct ReviewContinuePrompt: View {
    let facts: [Fact]

    private var pendingFacts: [Fact] {
        facts.filter { !$0.canAppearInDoctorView }
    }

    var body: some View {
        let count = pendingFacts.count
        VStack(spacing: 2) {
            Label(
                count == 1 ? "1 fact needs your review" : "\(count) facts need your review",
                systemImage: "exclamationmark.circle"
            )
            .font(.caption.weight(.semibold))
            .foregroundStyle(.orange)
            Text("Review each flagged fact, save edits, then confirm it before continuing.")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .accessibilityIdentifier(PatientAccessibilityIdentifier.reviewContinuePrompt)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Text("Review required before preparing a visit"))
        .accessibilityValue(Text(count == 1 ? "1 fact needs review" : "\(count) facts need review"))
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
                ProgressView("Uploading \(model.currentImportTitle)…")
                    .accessibilityIdentifier(PatientAccessibilityIdentifier.uploadProgress)
            case .processing:
                ProgressView("Processing \(model.currentImportTitle)…")
                    .accessibilityIdentifier(PatientAccessibilityIdentifier.uploadProgress)
            case let .reviewRequired(snapshot), let .completed(snapshot):
                Text(snapshot.ticket.title).font(.headline)
                if allowsReview {
                    List(snapshot.facts) { fact in
                        FactReviewRow(fact: fact, busy: model.isBusy) { value in
                            _Concurrency.Task { await model.editFact(fact, value: value) }
                        } confirm: {
                            _Concurrency.Task { await model.confirmFact(fact) }
                        }
                        .accessibilityIdentifier("\(PatientAccessibilityIdentifier.reviewFact).\(fact.id.uuidString)")
                    }
                    .accessibilityIdentifier(PatientAccessibilityIdentifier.reviewFactsList)
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

enum FactReviewIssue: String, CaseIterable, Hashable, Identifiable {
    case lowConfidence
    case missingSource
    case conflict
    case untraceable

    var id: Self { self }

    var title: String {
        switch self {
        case .lowConfidence: "Low confidence"
        case .missingSource: "Source missing"
        case .conflict: "Conflict needs review"
        case .untraceable: "Source cannot be verified"
        }
    }

    var guidance: String {
        switch self {
        case .lowConfidence: "Check this value against the original record before confirming."
        case .missingSource: "Add a patient-provided value or locate the supporting document."
        case .conflict: "This value changed or was rejected. Resolve it before continuing."
        case .untraceable: "The source belongs to another document, so it cannot be confirmed here."
        }
    }

    var systemImage: String {
        switch self {
        case .lowConfidence: "gauge.with.dots.needle.33percent"
        case .missingSource: "doc.questionmark"
        case .conflict: "arrow.triangle.2.circlepath"
        case .untraceable: "link.badge.plus"
        }
    }
}

extension Fact {
    var reviewIssues: [FactReviewIssue] {
        var issues: [FactReviewIssue] = []
        if confidence.map({ $0 < 0.8 }) ?? true {
            issues.append(.lowConfidence)
        }
        if sourceReference == nil && !isUserInput {
            issues.append(.missingSource)
        }
        if reviewStatus == .rejected || reviewStatus == .superseded {
            issues.append(.conflict)
        }
        if !isTraceable && !issues.contains(.missingSource) {
            issues.append(.untraceable)
        }
        return issues
    }

    var needsReviewAttention: Bool {
        !reviewIssues.isEmpty || !canAppearInDoctorView
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
            if !fact.reviewIssues.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(fact.reviewIssues) { issue in
                        VStack(alignment: .leading, spacing: 2) {
                            Label(issue.title, systemImage: issue.systemImage)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.orange)
                                .accessibilityIdentifier("\(PatientAccessibilityIdentifier.reviewFactIssue).\(fact.id.uuidString).\(issue.rawValue)")
                            Text(issue.guidance)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
                .accessibilityElement(children: .contain)
            }
            TextField("Fact", text: $value)
            if let source = fact.sourceReference {
                NavigationLink {
                    SourceLocatorView(reference: source)
                } label: {
                    Label("Open source \(source.locator)", systemImage: "location.viewfinder")
                        .font(.caption)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .accessibilityIdentifier("\(PatientAccessibilityIdentifier.reviewFactSource).\(fact.id.uuidString)")
                Text("Source document: \(source.documentID.uuidString)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            } else {
                Label(
                    fact.isUserInput ? "Patient-entered value" : "Source required before confirmation",
                    systemImage: fact.isUserInput ? "person.text.rectangle" : "doc.questionmark"
                )
                .font(.caption)
                .foregroundStyle(fact.isUserInput ? Color.secondary : Color.orange)
            }
            HStack {
                Button("Save edit") { edit(value) }
                    .disabled(busy || value == fact.value || value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("Confirm reviewed fact", action: confirm)
                    .disabled(busy || value != fact.value || fact.state != .needsReview || !fact.isTraceable)
                    .accessibilityIdentifier("\(PatientAccessibilityIdentifier.reviewFactConfirm).\(fact.id.uuidString)")
            }
            .buttonStyle(.bordered)
            if value != fact.value { Text("Save your edit before confirming.").font(.caption) }
        }
        .onChange(of: fact.value) { _, newValue in value = newValue }
        .padding(.vertical, 6)
    }
}

struct SourceLocatorView: View {
    let reference: SourceReference

    var body: some View {
        List {
            Section("Source location") {
                Label(reference.locator, systemImage: "location.viewfinder")
                    .font(.body.weight(.medium))
                    .textSelection(.enabled)
                    .accessibilityLabel(Text("Source location"))
                    .accessibilityValue(Text(reference.locator))
                ShareLink(item: reference.locator) {
                    Label("Share locator", systemImage: "square.and.arrow.up")
                }
                .accessibilityIdentifier("patient.source.share-locator")
            }
            Section("Source document") {
                Text(reference.documentID.uuidString)
                    .font(.footnote.monospaced())
                    .textSelection(.enabled)
                    .accessibilityLabel(Text("Source document identifier"))
            }
            Section {
                Text("Use this location to compare the fact with the original record before confirming it.")
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .navigationTitle("Source")
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
