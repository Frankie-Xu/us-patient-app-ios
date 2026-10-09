import Foundation
import SwiftUI
import PatientAppDomain

/// A deterministic, review-gated doctor brief built from confirmed facts.
struct DoctorBriefView: View {
    @ObservedObject var model: ImportFlowModel

    var body: some View {
        Group {
            if let snapshot = model.currentSnapshot, model.canPrepareVisit {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        Text("Doctor brief")
                            .font(.title2.weight(.semibold))
                        Text("Prepared from confirmed facts in \(snapshot.ticket.title).")
                            .foregroundStyle(.secondary)
                        SectionCard(title: "Summary", systemImage: "doc.text.magnifyingglass") {
                            Text(summary(for: snapshot))
                        }
                        SectionCard(title: "Confirmed facts", systemImage: "checkmark.seal") {
                            ForEach(snapshot.facts.filter(\.canAppearInDoctorView)) { fact in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("Confirmed fact").font(.headline)
                                    Text(fact.value)
                                    if let source = fact.sourceReference {
                                        NavigationLink {
                                            SourceLocatorView(reference: source)
                                        } label: {
                                            Label("Open source \(source.locator)", systemImage: "location.viewfinder")
                                                .font(.caption)
                                        }
                                        .accessibilityIdentifier("patient.doctor-brief.source.\(fact.id.uuidString)")
                                    }
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        NavigationLink {
                            VisitQuestionsView(model: model)
                        } label: {
                            Label("Continue to visit questions", systemImage: "questionmark.bubble")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    .padding()
                }
            } else {
                ContentUnavailableView(
                    "Review facts first",
                    systemImage: "checkmark.circle",
                    description: Text("Low-confidence, missing-source, or conflicting facts must be confirmed before a doctor brief can be prepared.")
                )
            }
        }
        .navigationTitle("Doctor brief")
    }

    private func summary(for snapshot: ImportSnapshot) -> String {
        guard snapshot.facts.contains(where: \.canAppearInDoctorView) else {
            return "No confirmed facts are available yet."
        }
        return "Review the confirmed information with your clinician."
    }
}

struct VisitQuestionsView: View {
    @ObservedObject var model: ImportFlowModel
    @State private var questions: [VisitQuestion] = []
    @State private var draft = ""

    var body: some View {
        Group {
            if let snapshot = model.currentSnapshot, model.canPrepareVisit {
                Form {
                    Section("Suggested questions") {
                        if questions.isEmpty {
                            Text("No questions added yet.").foregroundStyle(.secondary)
                        } else {
                            ForEach(questions) { question in
                                Label(question.text, systemImage: "questionmark.circle")
                            }
                            .onDelete { questions.remove(atOffsets: $0) }
                        }
                    }
                    Section("Add a question") {
                        TextField("What do you want to ask?", text: $draft)
                        Button("Add question") {
                            let value = draft.trimmingCharacters(in: .whitespacesAndNewlines)
                            guard !value.isEmpty else { return }
                            questions.append(VisitQuestion(text: value))
                            draft = ""
                        }
                        .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    Section("Share") {
                        NavigationLink {
                            DocumentShareView(documentID: snapshot.ticket.documentID, version: 1)
                        } label: {
                            Label("Export and share record", systemImage: "square.and.arrow.up")
                        }
                    }
                }
            } else {
                ContentUnavailableView("Questions unavailable", systemImage: "questionmark.bubble", description: Text("Confirm the document facts before preparing questions."))
            }
        }
        .navigationTitle("Visit questions")
        .onAppear {
            guard questions.isEmpty, let snapshot = model.currentSnapshot else { return }
            questions = snapshot.facts.filter(\.canAppearInDoctorView).map { _ in
                VisitQuestion(text: "What should I know about this confirmed result?")
            }
        }
    }
}

private struct VisitQuestion: Identifiable, Hashable {
    let id: UUID
    let text: String

    init(id: UUID = UUID(), text: String) {
        self.id = id
        self.text = text
    }
}

struct DocumentShareView: View {
    let documentID: UUID
    let version: Int
    @EnvironmentObject private var shell: AppShellModel

    var body: some View {
        DocumentShareContent(documentID: documentID, version: version, model: shell.shareFlow)
    }
}

/// Observes the nested model directly so create/revoke changes update the
/// controls as well as the independently observed access-status section.
private struct DocumentShareContent: View {
    let documentID: UUID
    let version: Int
    @ObservedObject var model: ShareFlowModel
    @State private var pdfState: PDFState = .idle

    var body: some View {
        Form {
            Section("PDF") {
                switch pdfState {
                case .idle:
                    Button("Export PDF") { _Concurrency.Task { await exportPDF() } }
                case .exporting:
                    ProgressView("Preparing PDF…")
                case let .ready(artifact):
                    Text("PDF v\(artifact.documentVersion) ready")
                    ShareLink(item: artifact.data, preview: SharePreview("Patient record PDF")) {
                        Label("Share PDF", systemImage: "square.and.arrow.up")
                    }
                case .failed:
                    Text("PDF export failed.").foregroundStyle(.red)
                    Button("Try again") { _Concurrency.Task { await exportPDF() } }
                }
            }
            Section("Controlled access") {
                switch model.state {
                case .idle:
                    Button("Create 24-hour share") {
                        _Concurrency.Task { await model.createDocumentShare(documentID: documentID, version: version) }
                    }
                case .creating:
                    ProgressView("Creating share…")
                case let .created(creation), let .revoking(creation):
                    Text(creation.token).font(.system(.body, design: .monospaced)).textSelection(.enabled)
                    if let expiresAt = creation.share.expiresAt {
                        Text("Expires \(expiresAt, format: .dateTime.month().day().hour().minute())").font(.caption)
                    }
                    Button("Revoke share", role: .destructive) { _Concurrency.Task { await model.revoke() } }
                        .disabled(model.isBusy || model.accessStatus?.isAccessible == false)
                    if model.isBusy { ProgressView() }
                case .revoked:
                    Label("Share revoked", systemImage: "checkmark.shield")
                case .failed:
                    Text("Share could not be created.").foregroundStyle(.red)
                    Button("Try again") { _Concurrency.Task { await model.retry() } }
                }
            }
            ShareAccessStatusSection(model: model)
        }
        .navigationTitle("Share record")
    }

    private func exportPDF() async {
        pdfState = .exporting
        do {
            pdfState = .ready(try await model.exportPDF(documentID: documentID, version: version))
        } catch {
            pdfState = .failed
        }
    }
}

private enum PDFState {
    case idle
    case exporting
    case ready(PDFExportArtifact)
    case failed
}

private struct SectionCard<Content: View>: View {
    let title: String
    let systemImage: String
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: systemImage).font(.headline)
            content()
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
}

/// Displays server-reported access state separately from share creation state.
/// A status lookup may fail after a token was created, so the token remains
/// visible while this section offers an independent retry action.
struct ShareAccessStatusSection: View {
    @ObservedObject var model: ShareFlowModel

    var body: some View {
        Section("Access status") {
            switch model.statusState {
            case .idle:
                Label(model.statusLabel, systemImage: "questionmark.circle")
                    .foregroundStyle(.secondary)
                Text(model.statusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            case .refreshing:
                ProgressView(model.statusMessage)
                    .accessibilityIdentifier("share.status.refreshing")
            case let .loaded(status):
                Label(model.statusLabel, systemImage: icon(for: status.state))
                    .foregroundStyle(color(for: status.state))
                    .accessibilityIdentifier("share.status.\(status.state.rawValue)")
                Text(model.statusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let expiresAt = status.share.expiresAt, status.state != .revoked {
                    Text("Valid until \(expiresAt, format: .dateTime.month().day().hour().minute())")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if status.state != .revoked, model.shareCreation != nil {
                    Button("Refresh status") { _Concurrency.Task { await model.refreshStatus() } }
                        .disabled(model.isRefreshingStatus)
                }
            case .failed:
                Label(model.statusLabel, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
                Text(model.statusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let error = model.statusError {
                    Text(error.statusMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
                Button("Retry status") { _Concurrency.Task { await model.retryStatus() } }
                    .disabled(model.shareCreation == nil || model.isRefreshingStatus)
            }
        }
    }

    private func icon(for state: ShareAccessState) -> String {
        switch state {
        case .active: "checkmark.shield"
        case .expired: "clock.badge.exclamationmark"
        case .revoked: "xmark.shield"
        }
    }

    private func color(for state: ShareAccessState) -> Color {
        switch state {
        case .active: .green
        case .expired, .revoked: .secondary
        }
    }
}

private extension PatientAPIClientError {
    var statusMessage: String {
        switch self {
        case .unauthorized, .missingBearerToken: "Sign in to refresh this share status."
        case .forbidden: "You do not have permission to view this share status."
        case .notFound: "This share link is no longer available."
        case .shareExpired: "This share link has expired."
        case .shareRevoked: "This share link has been revoked."
        case .transport, .server: "The share status service is unavailable."
        case .decoding: "The share status response was not understood."
        case .invalidBaseURL, .invalidRequest, .validation, .versionConflict, .unsupported: "The share status request could not be completed."
        }
    }
}
