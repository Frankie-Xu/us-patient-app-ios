# TestFlight release preparation

The package currently ships as a Swift Package so it can be built and tested in CI. The
TestFlight workflow is intentionally configuration driven: it never stores signing
material, App Store Connect keys, or patient data in Git.

## One-time Xcode setup

1. Create an iOS app target in Xcode that consumes the apps/ios/Package.swift package.
2. Add the PatientAppUI resources to the app target and set the bundle identifier.
3. Create an App Store Connect API key with the minimum role needed to upload builds.
4. Store the certificate and provisioning profile in the repository or organization
   secret store as encrypted values. Use a dedicated CI keychain; do not commit .p12,
   .mobileprovision, or API key files.
5. Configure these repository variables/secrets:

| Name | Kind | Purpose |
| --- | --- | --- |
| IOS_XCODE_PROJECT | Variable | Path to the .xcodeproj or .xcworkspace |
| IOS_XCODE_SCHEME | Variable | Release scheme |
| IOS_EXPORT_OPTIONS | Variable | Path to an export-options plist |
| IOS_TESTFLIGHT_UPLOAD | Variable | true only when a real upload is intended |
| APPLE_TEAM_ID | Secret | Signing team |
| APP_STORE_CONNECT_KEY_ID | Secret | App Store Connect API key id |
| APP_STORE_CONNECT_ISSUER_ID | Secret | App Store Connect issuer id |
| APP_STORE_CONNECT_PRIVATE_KEY | Secret | API key contents, injected at runtime |

The workflow exits with a notice when IOS_XCODE_PROJECT is not configured. This keeps
package-only pull requests green while the Xcode host is being prepared. It performs a
real archive/upload only when all variables are set and IOS_TESTFLIGHT_UPLOAD=true.

## Release checklist

- swift test --package-path apps/ios passes on the release commit.
- English and Simplified Chinese strings are present in the app bundle.
- VoiceOver can identify import, retry, offline, and success states.
- Dynamic Type is enabled in the host target and no screen relies on fixed-size text.
- Loading, error, empty, offline, retry, and success states have a visible message and
  an accessible label.
- The release evidence artifact is attached to the workflow run.
- TestFlight processing is complete before external testers are invited.
