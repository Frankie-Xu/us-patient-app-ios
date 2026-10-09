import SwiftUI
import PatientAppDomain

public struct AccountView: View {
    @ObservedObject var model: AppShellModel
    @State private var identifier = ""
    @State private var password = ""
    @State private var isWorking = false

    public init(model: AppShellModel) {
        self.model = model
    }

    public var body: some View {
        NavigationStack {
            Form {
                Section("Session") {
                    switch model.authState {
                    case .signedOut:
                        Text("Sign in to load account-owned records and preparation history.")
                            .foregroundStyle(.secondary)
                    case let .signedIn(session):
                        Text("Signed in as \(session.identifier)")
                        Text("Session epoch \(session.epoch)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    case .expired:
                        Text("Your session expired. Sign in again to continue.")
                            .foregroundStyle(.red)
                    }

                    TextField(model.usesCredentialAuthentication ? "Username" : "Account identifier", text: $identifier)
                        .autocorrectionDisabled()
                        .textContentType(.username)
                    if model.usesCredentialAuthentication {
                        SecureField("Password", text: $password)
                            .textContentType(.password)
                    }

                    switch model.authState {
                    case .signedIn:
                        Button(model.usesCredentialAuthentication ? "Sign in as another account" : "Switch account") { submit(.switchAccount) }
                    case .signedOut, .expired:
                        Button("Sign in") { submit(.signIn) }
                    }

                    if case .signedIn = model.authState {
                        Button("Sign out", role: .destructive) {
                            _Concurrency.Task {
                                isWorking = true
                                await model.logout()
                                isWorking = false
                            }
                        }
                    }
                    if isWorking { ProgressView() }
                    if let error = model.authError {
                        Label(error, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.red)
                    }
                }

                Section("Privacy preview") {
                    Text("This shell keeps identity-provider and token handling behind the session boundary.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Account")
            .accessibilityIdentifier(PatientAccessibilityIdentifier.tabAccount)
        }
    }

    private enum Action {
        case signIn
        case switchAccount
    }

    private func submit(_ action: Action) {
        let value = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, !model.usesCredentialAuthentication || !password.isEmpty else { return }
        let secret = password
        _Concurrency.Task {
            isWorking = true
            switch action {
            case .signIn:
                if model.usesCredentialAuthentication {
                    _ = await model.signIn(username: value, password: secret)
                } else {
                    _ = await model.signIn(identifier: value)
                }
            case .switchAccount:
                if model.usesCredentialAuthentication {
                    _ = await model.signIn(username: value, password: secret)
                } else {
                    _ = await model.switchAccount(identifier: value)
                }
            }
            isWorking = false
        }
    }
}
