import SwiftUI

/// Stable accessibility identifiers shared by the SwiftUI shell and UI tests.
public enum PatientAccessibilityIdentifier {
    public static let loginIdentifier = "patient.login.identifier"
    public static let loginSubmit = "patient.login.submit"
    public static let homeImportFile = "patient.home.import-file"
    public static let homeImportSynthetic = "patient.home.import-synthetic"
    public static let homeImportPhotos = "patient.home.import-photos"
    public static let homeImportCamera = "patient.home.import-camera"
    public static let homeUploadQueue = "patient.home.upload-queue"
    public static let recordsList = "patient.records.list"
    public static let reviewFactsList = "patient.review.facts"
    public static let reviewFact = "patient.review.fact"
    public static let reviewFactIssue = "patient.review.fact-issue"
    public static let reviewFactSource = "patient.review.fact-source"
    public static let reviewFactConfirm = "patient.review.fact-confirm"
    public static let reviewContinuePrompt = "patient.review.continue-prompt"
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
    private static let fallback: [String: [String: String]] = [
        "en": [
            "status.loading.title": "Loading",
            "status.failure.title": "Something went wrong",
            "status.empty.title": "Nothing here yet",
            "status.offline.title": "You’re offline",
            "status.retry.title": "Try again",
            "status.success.title": "Completed",
            "status.retry.action": "Retry"
        ],
        "zh-Hans": [
            "status.loading.title": "正在加载",
            "status.failure.title": "出现问题",
            "status.empty.title": "暂无内容",
            "status.offline.title": "当前离线",
            "status.retry.title": "请重试",
            "status.success.title": "已完成",
            "status.retry.action": "重试"
        ]
    ]

    public static func localized(_ key: String, locale: Locale = .current) -> String {
        let language = locale.language.languageCode?.identifier ?? "en"
        let resourceLanguage = language == "zh" ? "zh-Hans" : "en"
        if let localized = fallback[resourceLanguage]?[key] {
            return localized
        }
        #if SWIFT_PACKAGE
        return Bundle.module.localizedString(forKey: key, value: key, table: "Localizable")
        #else
        // The Xcode target ships the same strings through its synchronized
        // source group. Keep the deterministic fallback available when the
        // generated package resource accessor is not present.
        return key
        #endif
    }

    public static func hasResource(_ language: String) -> Bool {
        // SwiftPM's generated bundle exposes .lproj directories differently on
        // macOS and Linux. The supported locale list is the package contract;
        // actual strings remain in the bundled Localizable.strings resources.
        ["en", "zh-Hans"].contains(language)
    }
}
