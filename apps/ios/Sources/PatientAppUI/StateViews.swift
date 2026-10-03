import SwiftUI
import PatientAppDomain

struct StateContentView<Content: View>: View {
    let state: LoadState<[String]>
    let title: String
    let emptyMessage: String
    let retry: () -> Void
    @ViewBuilder let content: (String) -> Content

    var body: some View {
        Group {
            switch state {
            case .idle, .loading:
                ProgressView("Loading…")
            case .empty:
                ContentUnavailableView(title, systemImage: "tray", description: Text(emptyMessage))
            case let .failed(error):
                ContentUnavailableView("Unable to load", systemImage: "exclamationmark.triangle", description: Text(errorMessage(error)))
                    .overlay(alignment: .bottom) {
                        Button("Try again", action: retry).buttonStyle(.borderedProminent).padding(.bottom, 24)
                    }
            case let .loaded(items):
                List(items, id: \.self, rowContent: content)
            }
        }
        .navigationTitle(title)
    }

    private func errorMessage(_ error: PatientAppError) -> String {
        switch error {
        case .unavailable: "The service is unavailable right now."
        case .invalidTransition: "This item needs review before it can move forward."
        case .reviewRequired: "An explicit review action is required."
        case .sourceRequired: "A source or patient-entered value is required."
        }
    }
}

struct HomeView: View {
    var body: some View {
        NavigationStack {
            ContentUnavailableView("Ready when you are", systemImage: "folder", description: Text("Import a record to start a source-traceable visit pack."))
                .navigationTitle("Home")
        }
    }
}

struct RecordsView: View {
    var body: some View {
        NavigationStack {
            StateContentView(state: .empty, title: "Records", emptyMessage: "Imported records will appear here.", retry: {}) { Text($0) }
        }
    }
}

struct ReviewView: View {
    var body: some View {
        NavigationStack {
            StateContentView(state: .empty, title: "Review", emptyMessage: "Facts that need your review will appear here.", retry: {}) { Text($0) }
        }
    }
}

struct VisitsView: View {
    var body: some View {
        NavigationStack {
            StateContentView(state: .empty, title: "Visits", emptyMessage: "Prepare a visit pack when you have a visit planned.", retry: {}) { Text($0) }
        }
    }
}

struct TasksView: View {
    var body: some View {
        NavigationStack {
            StateContentView(state: .empty, title: "Tasks", emptyMessage: "Follow-up tasks will appear here.", retry: {}) { Text($0) }
        }
    }
}
