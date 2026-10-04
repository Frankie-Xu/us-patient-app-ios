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
    @Published public var importFlow: ImportFlowModel
    @Published public var visitPreparation: VisitPreparationModel
    @Published public var accountHistory: AccountHistoryModel
    @Published public private(set) var authState: AuthState = .signedOut
    public let protectedCache: any ProtectedCache
    public let sessionStore: any SessionStore
    public let authSession: any AuthSession

    public init(client: any PatientAPIClient = DeterministicMockAPIClient(), protectedCache: any ProtectedCache = InMemoryProtectedCache(), sessionStore: (any SessionStore)? = nil, authSession: (any AuthSession)? = nil) {
        let auth: any AuthSession
        if let authSession {
            auth = authSession
        } else if let sessionStore {
            auth = (sessionStore as? any AuthSession) ?? SessionStoreAuthAdapter(store: sessionStore)
        } else {
            auth = InMemorySessionStore(cache: protectedCache)
        }
        let store: any SessionStore = auth
        self.protectedCache = protectedCache
        self.sessionStore = store
        self.authSession = auth
        self.importFlow = ImportFlowModel(client: client)
        self.visitPreparation = VisitPreparationModel(client: client, sessionStore: store)
        self.accountHistory = AccountHistoryModel(client: client, cache: protectedCache, sessionStore: store)
    }

    public func signIn(identifier: String) async -> AuthState {
        visitPreparation.invalidateSession()
        accountHistory.invalidateSession()
        authState = await authSession.signIn(identifier: identifier)
        return authState
    }

    public func switchAccount(identifier: String) async -> AuthState {
        visitPreparation.invalidateSession()
        accountHistory.invalidateSession()
        authState = await authSession.switchAccount(identifier: identifier)
        return authState
    }

    public func restoreSession() async -> AuthState {
        authState = await authSession.restore()
        return authState
    }

    public func retryRestore() async -> AuthState { await restoreSession() }

    public func expireSession() async {
        visitPreparation.invalidateSession()
        accountHistory.invalidateSession()
        await authSession.expire()
        authState = await authSession.authState()
    }

    public func logout() async {
        visitPreparation.invalidateSession()
        accountHistory.invalidateSession()
        await authSession.logout()
        authState = await authSession.authState()
    }
}

public struct AppShellView: View {
    @StateObject private var model: AppShellModel

    public init(client: any PatientAPIClient = DeterministicMockAPIClient()) {
        _model = StateObject(wrappedValue: AppShellModel(client: client))
    }

    public var body: some View {
        TabView(selection: $model.selection) {
            HomeView(model: model.importFlow).tabItem { Label(AppSection.home.title, systemImage: AppSection.home.systemImage) }.tag(AppSection.home)
            RecordsView(model: model.importFlow).tabItem { Label(AppSection.records.title, systemImage: AppSection.records.systemImage) }.tag(AppSection.records)
            ReviewView(model: model.importFlow).tabItem { Label(AppSection.review.title, systemImage: AppSection.review.systemImage) }.tag(AppSection.review)
            VisitsView(model: model.visitPreparation, history: model.accountHistory).tabItem { Label(AppSection.visits.title, systemImage: AppSection.visits.systemImage) }.tag(AppSection.visits)
            TasksView(model: model.visitPreparation, history: model.accountHistory).tabItem { Label(AppSection.tasks.title, systemImage: AppSection.tasks.systemImage) }.tag(AppSection.tasks)
        }
    }
}
