# Patient App iOS baseline

This directory is a Swift Package baseline for the iOS client shell. It contains:

- `PatientAppDomain`: SwiftUI-independent server-owned projections, lifecycle rules, review/source invariants, and repository seams.
- `PatientAppUI`: task-oriented SwiftUI navigation for Home, Records, Review, Visits, and Tasks, with empty, loading, failure, and retry states.
- `PatientApp`: the executable SwiftUI app entry point for opening the package in Xcode.

Build and test from this directory with:

```sh
swift build
swift test
```

The package intentionally has no API payloads, authentication, real records, or local persistence. Those decisions remain open in [`docs/wayfinder-map.md`](../../docs/wayfinder-map.md).
