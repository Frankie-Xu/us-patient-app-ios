import SwiftUI
import PatientAppDomain

struct VisitsView: View {
    @ObservedObject var model: VisitPreparationModel
    @ObservedObject var history: AccountHistoryModel
    @ObservedObject var share: ShareFlowModel
    @ObservedObject var pack: VisitPackModel
    @State private var sharingVisit: Visit?
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
                                Button("Share with clinician") { sharingVisit = visit }
                                    .buttonStyle(.bordered)
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
                                HistoryVisitRow(visit: visit, share: { sharingVisit = visit })
                            }
                        }
                    } else {
                        AccountHistoryStatusView(state: history.state) { await history.retry() }
                    }
                }
                Section { Text("Use fictional information in this development preview.").font(.footnote) }
            }
            .navigationTitle("Visits")
            .sheet(item: $sharingVisit) { visit in
                ShareVisitSheet(visit: visit, model: share, pack: pack)
            }
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
    let share: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(visit.title).font(.headline)
            if let scheduledAt = visit.scheduledAt {
                Text(scheduledAt, format: .dateTime.month().day().hour().minute())
            } else { Text("Appointment date not provided") }
            Text("Account record · Version \(visit.version)").font(.caption)
            Button("Share with clinician", action: share)
                .buttonStyle(.bordered)
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

private struct ShareVisitSheet: View {
    let visit: Visit
    @ObservedObject var model: ShareFlowModel
    @ObservedObject var pack: VisitPackModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Visit") {
                    Text(visit.title).font(.headline)
                    Text("Share version \(visit.version) for 24 hours.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                VisitPackSection(model: pack)

                switch model.state {
                case .idle:
                    Section {
                        Button("Create 24-hour share") {
                            _Concurrency.Task { await model.createVisitShare(for: visit) }
                        }
                        .disabled(model.isBusy)
                    }
                case .creating:
                    Section { ProgressView("Creating share…") }
                case .revoking:
                    Section { ProgressView("Revoking share…") }
                case let .created(creation):
                    ShareCreationSection(creation: creation, revoke: { _Concurrency.Task { await model.revoke() } }, busy: model.isBusy)
                case let .revoked(version):
                    Section("Share revoked") {
                        Text("The share token is no longer active.")
                        if let revokedAt = version.revokedAt {
                            Text(revokedAt, format: .dateTime.month().day().hour().minute())
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                case .failed:
                    Section {
                        if let error = model.error {
                            Text(error.shareMessage).foregroundStyle(.red)
                        }
                        Button("Try again") { _Concurrency.Task { await model.retry() } }
                            .disabled(model.isBusy)
                    }
                }
            }
            .navigationTitle("Share visit")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .onAppear {
                model.reset()
                pack.reset()
            }
            .task(id: visit.id) {
                await pack.load(visitID: visit.id)
            }
        }
    }
}

private struct VisitPackSection: View {
    @ObservedObject var model: VisitPackModel

    var body: some View {
        Section("Preparation pack") {
            switch model.state {
            case .idle:
                ProgressView("Preparing visit pack…")
            case .loading:
                ProgressView("Loading topics and tasks…")
            case let .loaded(pack):
                if pack.topics.isEmpty && pack.tasks.isEmpty {
                    Text("No topics or follow-up tasks are attached yet.")
                        .foregroundStyle(.secondary)
                } else {
                    if !pack.topics.isEmpty {
                        Text("Topics").font(.caption).foregroundStyle(.secondary)
                        ForEach(pack.topics) { topic in
                            Label(topic.name, systemImage: "tag")
                        }
                    }
                    if !pack.tasks.isEmpty {
                        Text("Follow-up tasks").font(.caption).foregroundStyle(.secondary)
                        ForEach(pack.tasks) { task in
                            Label(task.title, systemImage: "checklist")
                        }
                    }
                }
            case .failed:
                if let error = model.error {
                    Text(error.packMessage).foregroundStyle(.red)
                }
                Button("Try again") { _Concurrency.Task { await model.retry() } }
            }
        }
    }
}

private struct ShareCreationSection: View {
    let creation: ShareCreation
    let revoke: () -> Void
    let busy: Bool

    var body: some View {
        Section("Share token") {
            Text(creation.token)
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
            ShareLink(item: "Patient App visit share token: \(creation.token)") {
                Label("Share token", systemImage: "square.and.arrow.up")
            }
            if let expiresAt = creation.share.expiresAt {
                Text("Expires \(expiresAt, format: .dateTime.month().day().hour().minute())")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Button("Revoke share", role: .destructive, action: revoke)
                .disabled(busy)
        }
    }
}

private extension PatientAPIClientError {
    var packMessage: String {
        switch self {
        case .notFound: "This visit is no longer available."
        case .unauthorized, .missingBearerToken: "Sign in to load visit preparation."
        case .forbidden: "You do not have permission to load this visit."
        case .unsupported: "Visit preparation is unavailable with the current service."
        case .server, .transport, .decoding, .invalidBaseURL, .invalidRequest, .validation, .versionConflict: "Visit preparation could not be loaded."
        }
    }

    var shareMessage: String {
        switch self {
        case .invalidRequest, .validation: "The share request is no longer valid."
        case .unauthorized, .missingBearerToken: "Sign in before sharing this visit."
        case .forbidden: "You do not have permission to share this visit."
        case .notFound: "This visit is no longer available."
        case .versionConflict: "This visit changed. Reload it before sharing."
        case .unsupported: "Sharing is unavailable with the current service."
        case .server, .transport, .decoding, .invalidBaseURL: "The share could not be created. Try again."
        }
    }
}
