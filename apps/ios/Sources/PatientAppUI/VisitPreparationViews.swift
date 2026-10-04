import SwiftUI
import PatientAppDomain

struct VisitsView: View {
    @ObservedObject var model: VisitPreparationModel
    @ObservedObject var history: AccountHistoryModel
    @State private var title = ""
    @State private var hasDate = false
    @State private var date = Date()

    var body: some View {
        NavigationStack {
            Form {
                Section("Add a visit") {
                    TextField("Visit title", text: $title)
                    Toggle("Set appointment date", isOn: $hasDate)
                    if hasDate { DatePicker("Appointment", selection: $date) }
                    Button("Save visit") {
                        _Concurrency.Task {
                            await model.createVisit(VisitCreateRequest(title: title, startsAt: hasDate ? date : nil))
                            if model.visitState.failure == nil { title = "" }
                        }
                    }
                    .disabled(model.visitState.isCreating || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                .disabled(model.visitState.isCreating)
                if model.visitState.isCreating {
                    Section { ProgressView("Saving visit…") }
                }
                if let failure = model.visitState.failure {
                    Section { CreationFailureView(failure: failure) { await model.retryVisit() } }
                }
                Section("Visits saved this session") {
                    if model.visitState.items.isEmpty {
                        ContentUnavailableView("No visits yet", systemImage: "calendar", description: Text("Add an appointment to organize your preparation."))
                    } else {
                        ForEach(model.visitState.items) { visit in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(visit.title).font(.headline)
                                if let date = visit.scheduledAt {
                                    Text(date, format: .dateTime.month().day().hour().minute())
                                } else { Text("Appointment date not provided") }
                                Text("\(visit.state.displayName) · Version \(visit.version)").font(.caption)
                            }
                        }
                    }
                }
                Section("Account history") {
                    if case let .loaded(snapshot) = history.state {
                        if snapshot.visits.isEmpty {
                            Text("No saved visits yet.").foregroundStyle(.secondary)
                        } else {
                            ForEach(snapshot.visits) { visit in
                                HistoryVisitRow(visit: visit)
                            }
                        }
                    } else {
                        AccountHistoryStatusView(state: history.state) { await history.retry() }
                    }
                }
                Section { Text("Use fictional information in this development preview.").font(.footnote) }
            }
            .navigationTitle("Visits")
            .task {
                if case .idle = history.state { await history.load() }
            }
        }
    }
}

struct TasksView: View {
    @ObservedObject var model: VisitPreparationModel
    @ObservedObject var history: AccountHistoryModel
    @State private var title = ""
    @State private var visitID: UUID?
    @State private var hasDate = false
    @State private var date = Date()

    var body: some View {
        NavigationStack {
            Form {
                Section("Add your next step") {
                    TextField("Task title", text: $title)
                    Picker("Related visit", selection: $visitID) {
                        Text("No related visit").tag(Optional<UUID>.none)
                        ForEach(model.visitState.items) { visit in
                            Text(visit.title).tag(Optional(visit.id))
                        }
                    }
                    Toggle("Set due date", isOn: $hasDate)
                    if hasDate { DatePicker("Due date", selection: $date, displayedComponents: .date) }
                    Button("Save task") {
                        _Concurrency.Task {
                            await model.createTask(TaskCreateRequest(title: title, visitID: visitID, dueAt: hasDate ? date : nil))
                            if model.taskState.failure == nil { title = "" }
                        }
                    }
                    .disabled(model.taskState.isCreating || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                .disabled(model.taskState.isCreating)
                if model.taskState.isCreating {
                    Section { ProgressView("Saving task…") }
                }
                if let failure = model.taskState.failure {
                    Section { CreationFailureView(failure: failure) { await model.retryTask() } }
                }
                Section("Tasks saved this session") {
                    if model.taskState.items.isEmpty {
                        ContentUnavailableView("No tasks yet", systemImage: "checklist", description: Text("Add a question or a step you want to follow up."))
                    } else {
                        ForEach(model.taskState.items) { task in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(task.title).font(.headline)
                                Text("Added by you · \(task.status.displayName)").font(.caption)
                                if let dueAt = task.dueAt { Text(dueAt, format: .dateTime.month().day().year()) }
                                else { Text("Due date not provided") }
                                if let related = model.visitState.items.first(where: { $0.id == task.visitID }) {
                                    Text("Visit: \(related.title)")
                                }
                                Text("Version \(task.version)").font(.caption)
                            }
                        }
                    }
                }
                Section("Account history") {
                    if case let .loaded(snapshot) = history.state {
                        if snapshot.tasks.isEmpty {
                            Text("No saved tasks yet.").foregroundStyle(.secondary)
                        } else {
                            ForEach(snapshot.tasks) { task in
                                HistoryTaskRow(task: task, visits: snapshot.visits)
                            }
                        }
                    } else {
                        AccountHistoryStatusView(state: history.state) { await history.retry() }
                    }
                }
                Section { Text("Use fictional information in this development preview.").font(.footnote) }
            }
            .navigationTitle("Tasks")
            .task {
                if case .idle = history.state { await history.load() }
            }
        }
    }
}

private struct CreationFailureView: View {
    let failure: CreationFailure
    let retry: () async -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(failure.message).foregroundStyle(.red)
            if failure.canRetry {
                Button("Try again") { _Concurrency.Task { await retry() } }
            }
        }
    }
}

private struct AccountHistoryStatusView: View {
    let state: AccountHistoryState
    let retry: () async -> Void

    var body: some View {
        switch state {
        case .idle:
            ProgressView("Loading account history…")
        case .loading:
            ProgressView("Loading account history…")
        case .empty:
            Text("No account history yet.").foregroundStyle(.secondary)
        case .loaded:
            EmptyView()
        case let .failed(error):
            VStack(alignment: .leading, spacing: 8) {
                Text(error.displayMessage).foregroundStyle(.red)
                Button("Try again") { _Concurrency.Task { await retry() } }
            }
        }
    }
}

private struct HistoryVisitRow: View {
    let visit: Visit

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(visit.title).font(.headline)
            if let scheduledAt = visit.scheduledAt {
                Text(scheduledAt, format: .dateTime.month().day().hour().minute())
            } else { Text("Appointment date not provided") }
            Text("Account record · Version \(visit.version)").font(.caption)
        }
    }
}

private struct HistoryTaskRow: View {
    let task: PatientAppDomain.Task
    let visits: [Visit]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(task.title).font(.headline)
            Text("Account record · \(task.status.displayName)").font(.caption)
            if let dueAt = task.dueAt { Text(dueAt, format: .dateTime.month().day().year()) }
            else { Text("Due date not provided") }
            if let visit = visits.first(where: { $0.id == task.visitID }) {
                Text("Visit: \(visit.title)")
            }
            Text("Version \(task.version)").font(.caption)
        }
    }
}

private extension TaskStatus {
    var displayName: String {
        switch self {
        case .open: "Open"
        case .completed: "Completed"
        case .cancelled: "Cancelled"
        }
    }
}

private extension PatientAPIClientError {
    var displayMessage: String {
        switch self {
        case .invalidBaseURL, .invalidRequest: "The account history request is invalid."
        case .missingBearerToken, .unauthorized: "Sign in to view your account history."
        case .forbidden: "You do not have permission to view this account history."
        case .notFound: "Account history is unavailable."
        case .versionConflict: "Account history changed. Try again."
        case .validation: "The account history request needs attention."
        case .server: "The account history service is unavailable."
        case .transport: "Could not load account history. Try again."
        case .decoding: "The service returned unsupported account history."
        case .unsupported: "Account history is unavailable with the current service."
        }
    }
}
