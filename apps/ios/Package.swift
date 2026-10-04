// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "PatientApp",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "PatientAppDomain", targets: ["PatientAppDomain"]),
        .library(name: "PatientAppUI", targets: ["PatientAppUI"]),
        .executable(name: "PatientApp", targets: ["PatientApp"])
    ],
    targets: [
        .target(name: "PatientAppDomain"),
        .target(name: "PatientAppUI", dependencies: ["PatientAppDomain"]),
        .executableTarget(name: "PatientApp", dependencies: ["PatientAppUI"]),
        .testTarget(name: "PatientAppDomainTests", dependencies: ["PatientAppDomain"]),
        .testTarget(name: "PatientAppUITests", dependencies: ["PatientAppUI", "PatientAppDomain"])
    ]
)
