import SwiftUI

/// Stable accessibility identifiers shared by the SwiftUI shell and UI tests.
public enum PatientAccessibilityIdentifier {
    public static let homeImportFile = "patient.home.import-file"
    public static let homeImportSynthetic = "patient.home.import-synthetic"
    public static let recordsList = "patient.records.list"
    public static let reviewFactsList = "patient.review.facts"
    public static let retry = "patient.retry"
    public static let offlineBanner = "patient.offline"
}

/// Statuses are intentionally explicit so VoiceOver users receive the same
/// loading, failure, empty, offline, retry and success feedback as sighted users.
public enum PatientStatusState: Equatable, Sendable, CaseIterable {
    case loading
    case failure
    case empty
    case offline
    case retry
    case success

    public var title: LocalizedStringKey {
        switch self {
        case .loading: "status.loading.title"
        case .failure: "status.failure.title"
        case .empty: "status.empty.title"
        case .offline: "status.offline.title"
        case .retry: "status.retry.title"
        case .success: "status.success.title"
        }
    }

    public var systemImage: String {
        switch self {
        case .loading: "hourglass"
        case .failure, .retry: "exclamationmark.triangle"
        case .empty: "tray"
        case .offline: "wifi.slash"
        case .success: "checkmark.circle"
        }
    }
}

/// A reusable status surface for screens that need a clear, accessible state.
public struct PatientStatusView: View {
    public let state: PatientStatusState
    public let message: String
    public let retry: (() -> Void)?

    public init(state: PatientStatusState, message: String = "", retry: (() -> Void)? = nil) {
        self.state = state
        self.message = message
        self.retry = retry
    }

    public var body: some View {
        VStack(spacing: 10) {
            if state == .loading {
                ProgressView()
                    .accessibilityLabel(Text("status.loading.title"))
            } else {
                Image(systemName: state.systemImage)
                    .imageScale(.large)
                    .accessibilityHidden(true)
            }

            Text(state.title)
                .font(.headline)
                .multilineTextAlignment(.center)

            if !message.isEmpty {
                Text(message)
                    .font(.body)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if state == .retry, let retry {
                Button("status.retry.action", action: retry)
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier(PatientAccessibilityIdentifier.retry)
            }
        }
        .frame(maxWidth: .infinity)
        .padding()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Text(state.title))
        .accessibilityValue(Text(message))
        .accessibilityAddTraits(state == .success ? .isStaticText : [])
    }
}

/// The package resource bundle is exposed through a small API so tests and
/// previews can verify that both supported locales are shipped.
public enum PatientLocalization {
    public static func localized(_ key: String, locale: Locale = .current) -> String {
        let language = locale.language.languageCode?.identifier ?? "en"
        let resourceLanguage = language == "zh" ? "zh-Hans" : "en"
        let bundlePath = Bundle.module.path(forResource: resourceLanguage, ofType: "lproj")
        let bundle = bundlePath.flatMap(Bundle.init(path:)) ?? Bundle.module
        return bundle.localizedString(forKey: key, value: key, table: "Localizable")
    }
}
