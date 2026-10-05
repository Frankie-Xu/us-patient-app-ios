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
                                        Label("Source \(source.locator)", systemImage: "location")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
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
    @State private var questions: [String] = []
    @State private var draft = ""

    var body: some View {
        Group {
            if let snapshot = model.currentSnapshot, model.canPrepareVisit {
                Form {
                    Section("Suggested questions") {
                        if questions.isEmpty {
                            Text("No questions added yet.").foregroundStyle(.secondary)
                        } else {
                            ForEach(questions, id: \.self) { question in
                                Label(question, systemImage: "questionmark.circle")
                            }
                            .onDelete { questions.remove(atOffsets: $0) }
                        }
                    }
                    Section("Add a question") {
                        TextField("What do you want to ask?", text: $draft)
                        Button("Add question") {
                            let value = draft.trimmingCharacters(in: .whitespacesAndNewlines)
                            guard !value.isEmpty else { return }
                            questions.append(value)
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
            questions = snapshot.facts.filter(\.canAppearInDoctorView).map { _ in "What should I know about this confirmed result?" }
        }
    }
}

struct DocumentShareView: View {
    let documentID: UUID
    let version: Int
    @EnvironmentObject private var shell: AppShellModel
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
                switch shell.shareFlow.state {
                case .idle:
                    Button("Create 24-hour share") {
                        _Concurrency.Task { await shell.shareFlow.createDocumentShare(documentID: documentID, version: version) }
                    }
                case .creating:
                    ProgressView("Creating share…")
                case let .created(creation), let .revoking(creation):
                    Text(creation.token).font(.system(.body, design: .monospaced)).textSelection(.enabled)
                    if let expiresAt = creation.share.expiresAt {
                        Text("Expires \(expiresAt, format: .dateTime.month().day().hour().minute())").font(.caption)
                    }
                    Button("Revoke share", role: .destructive) { _Concurrency.Task { await shell.shareFlow.revoke() } }
                        .disabled(shell.shareFlow.isBusy)
                    if shell.shareFlow.isBusy { ProgressView() }
                case .revoked:
                    Label("Share revoked", systemImage: "checkmark.shield")
                case .failed:
                    Text("Share could not be created.").foregroundStyle(.red)
                    Button("Try again") { _Concurrency.Task { await shell.shareFlow.retry() } }
                }
            }
        }
        .navigationTitle("Share record")
        .onAppear { shell.shareFlow.reset() }
    }

    private func exportPDF() async {
        pdfState = .exporting
        do {
            pdfState = .ready(try await shell.shareFlow.exportPDF(documentID: documentID, version: version))
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
