import SwiftUI
import PatientAppDomain

/// Lightweight demo sign-in used by the local fixture. The session boundary is
/// real (Keychain on iOS), while the identity provider is intentionally mocked.
public struct SignInView: View {
    @ObservedObject private var model: AppShellModel
    @State private var identifier = "demo-patient"
    @State private var isWorking = false

    public init(model: AppShellModel) {
        self.model = model
    }

    public var body: some View {
        NavigationStack {
            Form {
                Section {
                    Image(systemName: "heart.text.square")
                        .font(.system(size: 48))
                        .foregroundStyle(.tint)
                        .frame(maxWidth: .infinity)
                        .accessibilityHidden(true)
                    Text("Patient records")
                        .font(.title2.weight(.semibold))
                        .frame(maxWidth: .infinity)
                    Text("Local demo mode uses de-identified fixture data. No production account or token is embedded.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section("Demo session") {
                    TextField("Account identifier", text: $identifier)
                        .textContentType(.username)
                        .autocorrectionDisabled()
                        .accessibilityIdentifier(PatientAccessibilityIdentifier.loginIdentifier)
                    Button {
                        signIn()
                    } label: {
                        if isWorking {
                            ProgressView()
                                .frame(maxWidth: .infinity)
                        } else {
                            Text("Continue with local fixture")
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isWorking || identifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityIdentifier(PatientAccessibilityIdentifier.loginSubmit)
                }

                if case .expired = model.authState {
                    Text("Your session expired. Continue to start a new local session.")
                        .font(.footnote)
                        .foregroundStyle(.orange)
                }
            }
            .navigationTitle("Sign in")
        }
    }

    private func signIn() {
        let value = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        isWorking = true
        _Concurrency.Task {
            _ = await model.signIn(identifier: value)
            isWorking = false
        }
    }
}
