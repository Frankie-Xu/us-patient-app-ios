import SwiftUI
import PatientAppDomain

/// Sign-in for both deterministic fixture mode and local staging. Fixture mode
/// keeps the one-field demo flow; staging always exchanges username/password
/// for a locally issued JWT and never derives a bearer value from the account.
public struct SignInView: View {
    @ObservedObject private var model: AppShellModel
    @State private var identifier = "demo-patient"
    @State private var username = Self.launchUsername
    @State private var password = Self.launchPassword
    @State private var isWorking = false

    public init(model: AppShellModel) {
        self.model = model
    }

    // UI automation may inject a de-identified local account through the
    // launch environment. No credentials are stored in source or prefilled in
    // normal app launches.
    private static var launchUsername: String {
        guard ProcessInfo.processInfo.arguments.contains("--patient-app-ui-test") else { return "" }
        return ProcessInfo.processInfo.environment["PATIENT_APP_STAGING_USERNAME"] ?? ""
    }

    private static var launchPassword: String {
        guard ProcessInfo.processInfo.arguments.contains("--patient-app-ui-test") else { return "" }
        return ProcessInfo.processInfo.environment["PATIENT_APP_STAGING_PASSWORD"] ?? ""
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
                    Text(model.usesCredentialAuthentication
                         ? "Staging sign-in uses a local development account over HTTPS."
                         : "Local demo mode uses de-identified fixture data. No production account or token is embedded.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if model.usesCredentialAuthentication {
                    Section("Staging account") {
                        TextField("Username", text: $username)
                            .textContentType(.username)
                            .autocorrectionDisabled()
                            .accessibilityIdentifier(PatientAccessibilityIdentifier.loginUsername)
                        SecureField("Password", text: $password)
                            .textContentType(.password)
                            .accessibilityIdentifier(PatientAccessibilityIdentifier.loginPassword)
                        Button {
                            signInStaging()
                        } label: {
                            if isWorking {
                                ProgressView().frame(maxWidth: .infinity)
                            } else {
                                Text("Sign in to staging").frame(maxWidth: .infinity)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(isWorking || username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || password.isEmpty)
                        .accessibilityIdentifier(PatientAccessibilityIdentifier.loginSubmit)
                    }
                } else {
                    Section("Demo session") {
                        TextField("Account identifier", text: $identifier)
                            .textContentType(.username)
                            .autocorrectionDisabled()
                            .accessibilityIdentifier(PatientAccessibilityIdentifier.loginIdentifier)
                        Button {
                            signInFixture()
                        } label: {
                            if isWorking {
                                ProgressView().frame(maxWidth: .infinity)
                            } else {
                                Text("Continue with local fixture").frame(maxWidth: .infinity)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(isWorking || identifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        .accessibilityIdentifier(PatientAccessibilityIdentifier.loginSubmit)
                    }
                }

                if let runtimeConfigurationError = model.runtimeConfigurationError {
                    Section("Staging configuration") {
                        Label(runtimeConfigurationError, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.orange)
                        Button("Retry staging configuration") {
                            _Concurrency.Task { _ = await model.retryRestore() }
                        }
                        .accessibilityIdentifier(PatientAccessibilityIdentifier.loginRetry)
                    }
                }

                if let authError = model.authError {
                    Section {
                        Label(authError, systemImage: "wifi.exclamationmark")
                            .foregroundStyle(.red)
                        Button("Try again") {
                            if model.usesCredentialAuthentication { signInStaging() }
                            else { signInFixture() }
                        }
                        .accessibilityIdentifier(PatientAccessibilityIdentifier.loginRetry)
                    }
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

    private func signInFixture() {
        let value = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        isWorking = true
        _Concurrency.Task {
            _ = await model.signIn(identifier: value)
            isWorking = false
        }
    }

    private func signInStaging() {
        let value = username.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, !password.isEmpty else { return }
        isWorking = true
        let secret = password
        _Concurrency.Task {
            _ = await model.signIn(username: value, password: secret)
            isWorking = false
        }
    }
}
