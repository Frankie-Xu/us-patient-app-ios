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
    @Published public private(set) var authError: String?
    /// Non-nil when an explicitly requested staging configuration could not be
    /// assembled. This is surfaced to the sign-in screen instead of silently
    /// switching the user back to deterministic mock data.
    public let runtimeConfigurationError: String?
    public let uploadQueue: OfflineUploadCoordinator
    public let client: any PatientAPIClient
    public let protectedCache: any ProtectedCache
    public let sessionStore: any SessionStore
    public let authSession: any AuthSession

    public init(client: any PatientAPIClient = DeterministicMockAPIClient(), protectedCache: any ProtectedCache = InMemoryProtectedCache(), sessionStore: (any SessionStore)? = nil, authSession: (any AuthSession)? = nil, uploadQueuePersistence: (any UploadQueuePersistence)? = nil, runtimeConfigurationError: String? = nil) {
        self.client = client
        self.runtimeConfigurationError = runtimeConfigurationError
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
        authError = nil
        await uploadQueue.restore()
        return authState
    }

    /// Signs in against a credential-aware provider. Fixture sessions keep the
    /// existing identifier-only API; staging sessions use real local JWTs.
    public func signIn(username: String, password: String) async -> AuthState {
        visitPreparation.invalidateSession()
        shareFlow.reset()
        visitPack.reset()
        accountHistory.invalidateSession()
        documentHistory.invalidateSession()
        guard let credentialSession = authSession as? any CredentialAuthSession else {
            authError = "Credential sign-in is unavailable in local fixture mode."
            return authState
        }
        do {
            authState = try await credentialSession.signIn(username: username, password: password)
            authError = nil
            await uploadQueue.restore()
        } catch {
            authError = Self.authErrorMessage(error)
            authState = await authSession.authState()
        }
        return authState
    }

    public func switchAccount(identifier: String) async -> AuthState {
        visitPreparation.invalidateSession()
        shareFlow.reset()
        visitPack.reset()
        accountHistory.invalidateSession()
        documentHistory.invalidateSession()
        authState = await authSession.switchAccount(identifier: identifier)
        authError = nil
        await uploadQueue.restore()
        return authState
    }

    public func restoreSession() async -> AuthState {
        if runtimeConfigurationError != nil {
            // Drop any stale fixture session that may be in the Keychain. An
            // explicit staging configuration error must never render as a
            // signed-in mock session.
            await authSession.logout()
            authState = .signedOut
            authError = runtimeConfigurationError
            return authState
        }
        if let credentialSession = authSession as? any CredentialAuthSession {
            do {
                authState = try await credentialSession.restoreCredentials()
                authError = nil
            } catch {
                authError = Self.authErrorMessage(error)
                authState = await authSession.authState()
            }
        } else {
            authState = await authSession.restore()
        }
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
        authError = nil
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
        authError = nil
    }

    public var usesCredentialAuthentication: Bool {
        authSession is any CredentialAuthSession || runtimeConfigurationError != nil
    }

    private static func authErrorMessage(_ error: Error) -> String {
        switch error {
        case AuthSessionError.invalidCredentials:
            return "The username or password is incorrect."
        case AuthSessionError.unavailable:
            return "Staging is unavailable. Check the connection and try again."
        case AuthSessionError.invalidResponse:
            return "Staging returned an invalid sign-in response. Try again."
        case AuthSessionError.configuration:
            return "Staging configuration is invalid. Check the HTTPS URL and try again."
        default:
            return "Sign-in failed. Check the connection and try again."
        }
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
            if ProcessInfo.processInfo.arguments.contains("--patient-app-demo-signed-in") {
                _ = await model.signIn(identifier: "demo-patient")
                if ProcessInfo.processInfo.arguments.contains("--patient-app-demo-imported") {
                    let content = Data("synthetic fixture content".utf8)
                    await model.importFlow.start(
                        ImportRequest(
                            fileName: "synthetic-record.txt",
                            title: "Synthetic record",
                            byteCount: content.count,
                            mediaType: "text/plain",
                            sha256: String(repeating: "0", count: 64),
                            content: content
                        )
                    )
                }
            } else {
                _ = await model.restoreSession()
            }
        }
    }

    @ViewBuilder
    private var authenticatedContent: some View {
        TabView(selection: $model.selection) {
            HomeView(model: model.importFlow, uploadQueue: model.uploadQueue).tabItem { Label(AppSection.home.title, systemImage: AppSection.home.systemImage) }.tag(AppSection.home)
            RecordsView(model: model.importFlow, history: model.documentHistory, client: model.client, onReview: { model.selection = .review }).tabItem { Label(AppSection.records.title, systemImage: AppSection.records.systemImage) }.tag(AppSection.records)
            ReviewView(model: model.importFlow).tabItem { Label(AppSection.review.title, systemImage: AppSection.review.systemImage) }.tag(AppSection.review)
            VisitsView(model: model.visitPreparation, history: model.accountHistory, share: model.shareFlow, pack: model.visitPack).tabItem { Label(AppSection.visits.title, systemImage: AppSection.visits.systemImage) }.tag(AppSection.visits)
            TasksView(model: model.visitPreparation, history: model.accountHistory).tabItem { Label(AppSection.tasks.title, systemImage: AppSection.tasks.systemImage) }.tag(AppSection.tasks)
            AccountView(model: model).tabItem { Label(AppSection.account.title, systemImage: AppSection.account.systemImage) }.tag(AppSection.account)
        }
        .environmentObject(model)
        .task {
            await model.uploadQueue.restore()
        }
    }
}
