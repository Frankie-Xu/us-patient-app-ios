import SwiftUI
import PatientAppDomain

public enum AppSection: String, CaseIterable, Identifiable, Sendable {
    case home, records, review, visits, tasks, account

    public var id: Self { self }

    public var title: String {
        switch self {
        case .home: "Home"
        case .records: "Records"
        case .review: "Review"
        case .visits: "Visits"
        case .tasks: "Tasks"
        case .account: "Account"
        }
    }

    public var systemImage: String {
        switch self {
        case .home: "house"
        case .records: "doc.text"
        case .review: "checkmark.circle"
        case .visits: "calendar"
        case .tasks: "checklist"
        case .account: "person.crop.circle"
        }
    }
}

@MainActor
public final class AppShellModel: ObservableObject {
    @Published public var selection: AppSection = .home
    @Published public var importFlow: ImportFlowModel
    @Published public var visitPreparation: VisitPreparationModel
    @Published public var shareFlow: ShareFlowModel
    @Published public var visitPack: VisitPackModel
    @Published public var accountHistory: AccountHistoryModel
    @Published public var documentHistory: DocumentHistoryModel
    @Published public private(set) var authState: AuthState = .signedOut
    public let uploadQueue: OfflineUploadCoordinator
    public let protectedCache: any ProtectedCache
    public let sessionStore: any SessionStore
    public let authSession: any AuthSession

    public init(client: any PatientAPIClient = DeterministicMockAPIClient(), protectedCache: any ProtectedCache = InMemoryProtectedCache(), sessionStore: (any SessionStore)? = nil, authSession: (any AuthSession)? = nil, uploadQueuePersistence: (any UploadQueuePersistence)? = nil) {
        let auth: any AuthSession
        if let authSession {
            auth = authSession
        } else if let sessionStore {
            auth = (sessionStore as? any AuthSession) ?? SessionStoreAuthAdapter(store: sessionStore)
        } else {
            auth = InMemorySessionStore(cache: protectedCache)
        }
        let store: any SessionStore = auth
        self.uploadQueue = OfflineUploadCoordinator(client: client, persistence: uploadQueuePersistence ?? InMemoryUploadQueuePersistence())
        self.protectedCache = protectedCache
        self.sessionStore = store
        self.authSession = auth
        self.importFlow = ImportFlowModel(client: client)
        self.visitPreparation = VisitPreparationModel(client: client, sessionStore: store)
        self.shareFlow = ShareFlowModel(client: client)
        self.visitPack = VisitPackModel(client: client)
        self.accountHistory = AccountHistoryModel(client: client, cache: protectedCache, sessionStore: store)
        self.documentHistory = DocumentHistoryModel(client: client)
    }

    public func signIn(identifier: String) async -> AuthState {
        visitPreparation.invalidateSession()
        shareFlow.reset()
        visitPack.reset()
        accountHistory.invalidateSession()
        documentHistory.invalidateSession()
        authState = await authSession.signIn(identifier: identifier)
        await uploadQueue.restore()
        return authState
    }

    public func switchAccount(identifier: String) async -> AuthState {
        visitPreparation.invalidateSession()
        shareFlow.reset()
        visitPack.reset()
        accountHistory.invalidateSession()
        documentHistory.invalidateSession()
        authState = await authSession.switchAccount(identifier: identifier)
        await uploadQueue.restore()
        return authState
    }

    public func restoreSession() async -> AuthState {
        authState = await authSession.restore()
        return authState
    }

    public func retryRestore() async -> AuthState { await restoreSession() }

    public func expireSession() async {
        visitPreparation.invalidateSession()
        shareFlow.reset()
        visitPack.reset()
        accountHistory.invalidateSession()
        documentHistory.invalidateSession()
        await authSession.expire()
        await uploadQueue.restore()
        authState = await authSession.authState()
    }

    public func logout() async {
        visitPreparation.invalidateSession()
        shareFlow.reset()
        visitPack.reset()
        accountHistory.invalidateSession()
        documentHistory.invalidateSession()
        await authSession.logout()
        await uploadQueue.restore()
        authState = await authSession.authState()
    }
}

public struct AppShellView: View {
    @StateObject private var model: AppShellModel

    /// The application target uses the real URLSession composition by default.
    /// Tests and previews can inject the deterministic client explicitly.
    public init(client: (any PatientAPIClient)? = nil) {
        let model = client.map { AppShellModel(client: $0) } ?? PatientAppRuntime.makeModel()
        _model = StateObject(wrappedValue: model)
    }

    public var body: some View {
        Group {
            switch model.authState {
            case .signedIn:
                authenticatedContent
            case .signedOut, .expired:
                SignInView(model: model)
            }
        }
        .task {
            _ = await model.restoreSession()
        }
    }

    @ViewBuilder
    private var authenticatedContent: some View {
        TabView(selection: $model.selection) {
            HomeView(model: model.importFlow, uploadQueue: model.uploadQueue).tabItem { Label(AppSection.home.title, systemImage: AppSection.home.systemImage) }.tag(AppSection.home)
            RecordsView(model: model.importFlow, history: model.documentHistory, onReview: { model.selection = .review }).tabItem { Label(AppSection.records.title, systemImage: AppSection.records.systemImage) }.tag(AppSection.records)
            ReviewView(model: model.importFlow).tabItem { Label(AppSection.review.title, systemImage: AppSection.review.systemImage) }.tag(AppSection.review)
            VisitsView(model: model.visitPreparation, history: model.accountHistory, share: model.shareFlow, pack: model.visitPack).tabItem { Label(AppSection.visits.title, systemImage: AppSection.visits.systemImage) }.tag(AppSection.visits)
            TasksView(model: model.visitPreparation, history: model.accountHistory).tabItem { Label(AppSection.tasks.title, systemImage: AppSection.tasks.systemImage) }.tag(AppSection.tasks)
            AccountView(model: model).tabItem { Label(AppSection.account.title, systemImage: AppSection.account.systemImage) }.tag(AppSection.account)
        }
        .task {
            await model.uploadQueue.restore()
        }
    }
}
