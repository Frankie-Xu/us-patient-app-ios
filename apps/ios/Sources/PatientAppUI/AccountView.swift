import SwiftUI
import PatientAppDomain

public struct AccountView: View {
    @ObservedObject var model: AppShellModel
    @State private var identifier = ""
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

                    TextField("Account identifier", text: $identifier)
                        .autocorrectionDisabled()

                    switch model.authState {
                    case .signedIn:
                        Button("Switch account") { submit(.switchAccount) }
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
        guard !value.isEmpty else { return }
        _Concurrency.Task {
            isWorking = true
            switch action {
            case .signIn:
                _ = await model.signIn(identifier: value)
            case .switchAccount:
                _ = await model.switchAccount(identifier: value)
            }
            isWorking = false
        }
    }
}
