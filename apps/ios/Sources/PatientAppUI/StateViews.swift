import SwiftUI
import PatientAppDomain

struct HomeView: View {
    @ObservedObject var model: ImportFlowModel
    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                Text("Synthetic record workspace").font(.title2)
                Text("Try the import and review flow with fictional content.")
                Button("Import synthetic record") {
                    _Concurrency.Task {
                        await model.start(ImportRequest(fileName: "synthetic-record.txt", title: "Synthetic record"))
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.isBusy)
                FlowContent(model: model, allowsReview: false)
            }
            .padding()
            .navigationTitle("Home")
        }
    }
}

struct RecordsView: View {
    @ObservedObject var model: ImportFlowModel
    var body: some View {
        NavigationStack {
            FlowContent(model: model, allowsReview: false).navigationTitle("Records")
        }
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

struct VisitsView: View {
    var body: some View {
        NavigationStack {
            ContentUnavailableView("No visits", systemImage: "calendar", description: Text("Visit preparation will be available in a later phase."))
                .navigationTitle("Visits")
        }
    }
}

struct TasksView: View {
    var body: some View {
        NavigationStack {
            ContentUnavailableView("No tasks", systemImage: "checklist", description: Text("Follow-up tasks will appear here."))
                .navigationTitle("Tasks")
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
        case .invalidTransition: "This action is unavailable in the current state."
        case .unavailable: "The operation is temporarily unavailable."
        }
    }
}
