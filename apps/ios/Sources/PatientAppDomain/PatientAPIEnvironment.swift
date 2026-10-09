import Foundation

/// Selects the API environment without embedding a deployment URL in the app.
///
/// The app remains on the local deterministic fixture unless staging is
/// explicitly requested with a launch argument or environment variable. A
/// staging URL must be HTTPS and include a host; malformed values are rejected
/// before a live URLSession client can be created.
public struct PatientAPIEnvironmentConfiguration: Equatable, Sendable {
    public enum Mode: String, Equatable, Sendable {
        case mock
        case staging
    }

    public enum ResolutionError: Error, Equatable, Sendable {
        case missingStagingBaseURL
        case invalidStagingBaseURL
        case unsupportedEnvironment(String)
    }

    public static let environmentKey = "PATIENT_APP_ENV"
    public static let stagingBaseURLKey = "PATIENT_APP_STAGING_BASE_URL"
    public static let stagingFlag = "--patient-app-staging"
    public static let baseURLArgument = "--patient-app-api-base-url"

    public let mode: Mode
    public let baseURL: URL?

    public init(mode: Mode, baseURL: URL? = nil) throws {
        switch mode {
        case .mock:
            guard baseURL == nil else { throw ResolutionError.invalidStagingBaseURL }
        case .staging:
            guard let baseURL, Self.isValidStagingURL(baseURL) else {
                throw ResolutionError.invalidStagingBaseURL
            }
        }
        self.mode = mode
        self.baseURL = baseURL
    }

    /// Resolves process launch arguments and environment variables. Supported
    /// inputs are intentionally small and explicit so a production build cannot
    /// silently turn an arbitrary URL into a live API client:
    ///
    /// * `--patient-app-staging` plus `PATIENT_APP_STAGING_BASE_URL`
    /// * `--patient-app-api-base-url https://...` (or `=https://...`)
    /// * `PATIENT_APP_ENV=staging` plus `PATIENT_APP_STAGING_BASE_URL`
    public static func resolve(
        arguments: [String],
        environment: [String: String]
    ) throws -> PatientAPIEnvironmentConfiguration {
        let argumentURL = value(for: baseURLArgument, in: arguments)
        let environmentMode = environment[environmentKey]?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if let environmentMode, !environmentMode.isEmpty, environmentMode != Mode.mock.rawValue, environmentMode != Mode.staging.rawValue {
            throw ResolutionError.unsupportedEnvironment(environmentMode)
        }

        let stagingRequested = arguments.contains(stagingFlag)
            || argumentURL != nil
            || environmentMode == Mode.staging.rawValue
            || isTruthy(environment["PATIENT_APP_STAGING"])
        guard stagingRequested else {
            return try PatientAPIEnvironmentConfiguration(mode: .mock)
        }

        let rawURL = argumentURL ?? environment[stagingBaseURLKey]
        guard let rawURL, !rawURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ResolutionError.missingStagingBaseURL
        }
        guard let url = URL(string: rawURL.trimmingCharacters(in: .whitespacesAndNewlines)), isValidStagingURL(url) else {
            throw ResolutionError.invalidStagingBaseURL
        }
        return try PatientAPIEnvironmentConfiguration(mode: .staging, baseURL: url)
    }

    private static func value(for key: String, in arguments: [String]) -> String? {
        guard let index = arguments.firstIndex(where: { $0 == key || $0.hasPrefix("\(key)=") }) else { return nil }
        let argument = arguments[index]
        if let equals = argument.firstIndex(of: "=") {
            return String(argument[argument.index(after: equals)...])
        }
        let next = arguments.index(after: index)
        guard next < arguments.endIndex else { return nil }
        return arguments[next]
    }

    private static func isTruthy(_ value: String?) -> Bool {
        guard let value else { return false }
        return ["1", "true", "yes", "on"].contains(value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
    }

    private static func isValidStagingURL(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https"
            && url.host?.isEmpty == false
            && url.user == nil
            && url.password == nil
            && url.query == nil
            && url.fragment == nil
    }
}
