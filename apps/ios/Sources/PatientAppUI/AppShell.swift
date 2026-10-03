import SwiftUI
import PatientAppDomain

public enum AppSection: String, CaseIterable, Identifiable, Sendable {
    case home, records, review, visits, tasks

    public var id: Self { self }

    public var title: String {
        switch self {
        case .home: "Home"
        case .records: "Records"
        case .review: "Review"
        case .visits: "Visits"
        case .tasks: "Tasks"
        }
    }

    public var systemImage: String {
        switch self {
        case .home: "house"
        case .records: "doc.text"
        case .review: "checkmark.circle"
        case .visits: "calendar"
        case .tasks: "checklist"
        }
    }
}

@MainActor
public final class AppShellModel: ObservableObject {
    @Published public var selection: AppSection = .home
    public init() {}
}

public struct AppShellView: View {
    @StateObject private var model = AppShellModel()

    public init() {}

    public var body: some View {
        TabView(selection: $model.selection) {
            HomeView().tabItem { Label(AppSection.home.title, systemImage: AppSection.home.systemImage) }.tag(AppSection.home)
            RecordsView().tabItem { Label(AppSection.records.title, systemImage: AppSection.records.systemImage) }.tag(AppSection.records)
            ReviewView().tabItem { Label(AppSection.review.title, systemImage: AppSection.review.systemImage) }.tag(AppSection.review)
            VisitsView().tabItem { Label(AppSection.visits.title, systemImage: AppSection.visits.systemImage) }.tag(AppSection.visits)
            TasksView().tabItem { Label(AppSection.tasks.title, systemImage: AppSection.tasks.systemImage) }.tag(AppSection.tasks)
        }
    }
}
