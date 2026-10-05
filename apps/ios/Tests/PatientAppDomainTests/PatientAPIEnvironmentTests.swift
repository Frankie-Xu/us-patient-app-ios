import XCTest
@testable import PatientAppDomain

final class PatientAPIEnvironmentTests: XCTestCase {
    func testDefaultResolutionStaysOnMock() throws {
        let configuration = try PatientAPIEnvironmentConfiguration.resolve(arguments: [], environment: [:])
        XCTAssertEqual(configuration.mode, .mock)
        XCTAssertNil(configuration.baseURL)
    }

    func testStagingResolvesFromEnvironment() throws {
        let configuration = try PatientAPIEnvironmentConfiguration.resolve(
            arguments: ["PatientApp", PatientAPIEnvironmentConfiguration.stagingFlag],
            environment: [PatientAPIEnvironmentConfiguration.stagingBaseURLKey: "https://staging.example.test/api"]
        )
        XCTAssertEqual(configuration.mode, .staging)
        XCTAssertEqual(configuration.baseURL?.absoluteString, "https://staging.example.test/api")
    }

    func testStagingResolvesFromLaunchArgument() throws {
        let configuration = try PatientAPIEnvironmentConfiguration.resolve(
            arguments: ["PatientApp", "\(PatientAPIEnvironmentConfiguration.baseURLArgument)=https://staging.example.test"],
            environment: [:]
        )
        XCTAssertEqual(configuration.baseURL?.host, "staging.example.test")
    }

    func testStagingRejectsMissingURL() {
        XCTAssertThrowsError(try PatientAPIEnvironmentConfiguration.resolve(
            arguments: [PatientAPIEnvironmentConfiguration.stagingFlag],
            environment: [:]
        )) { error in
            XCTAssertEqual(error as? PatientAPIEnvironmentConfiguration.ResolutionError, .missingStagingBaseURL)
        }
    }

    func testStagingRejectsInsecureOrHostlessURL() {
        for rawURL in ["http://staging.example.test", "https:///api", "https://"] {
            XCTAssertThrowsError(try PatientAPIEnvironmentConfiguration.resolve(
                arguments: [PatientAPIEnvironmentConfiguration.stagingFlag],
                environment: [PatientAPIEnvironmentConfiguration.stagingBaseURLKey: rawURL]
            ), "expected staging URL to be rejected: \(rawURL)") { error in
                XCTAssertEqual(error as? PatientAPIEnvironmentConfiguration.ResolutionError, .invalidStagingBaseURL)
            }
        }
    }

    func testMockFlagTakesPriorityAtRuntimeBoundary() throws {
        let configuration = try PatientAPIEnvironmentConfiguration.resolve(
            arguments: [],
            environment: [PatientAPIEnvironmentConfiguration.environmentKey: "mock"]
        )
        XCTAssertEqual(configuration.mode, .mock)
    }
}
