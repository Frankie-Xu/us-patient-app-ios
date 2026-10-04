import XCTest
@testable import PatientAppUI

final class AccessibilityLocalizationTests: XCTestCase {
    func testAllAccessibleStatesHaveStablePresentation() {
        let states: [PatientStatusState] = [.loading, .failure, .empty, .offline, .retry, .success]
        XCTAssertEqual(states.count, PatientStatusState.allCases.count)
        XCTAssertTrue(states.allSatisfy { !$0.systemImage.isEmpty })
    }

    func testEnglishAndSimplifiedChineseResourcesShip() {
        let module = Bundle.module
        XCTAssertNotNil(module.url(forResource: "en", withExtension: "lproj"))
        XCTAssertNotNil(module.url(forResource: "zh-Hans", withExtension: "lproj"))

        XCTAssertEqual(
            PatientLocalization.localized("status.loading.title", locale: Locale(identifier: "en_US")),
            "Loading"
        )
        XCTAssertEqual(
            PatientLocalization.localized("status.loading.title", locale: Locale(identifier: "zh-Hans")),
            "正在加载"
        )
    }

    func testAccessibilityIdentifiersRemainStable() {
        XCTAssertEqual(PatientAccessibilityIdentifier.homeImportFile, "patient.home.import-file")
        XCTAssertEqual(PatientAccessibilityIdentifier.retry, "patient.retry")
        XCTAssertEqual(PatientAccessibilityIdentifier.offlineBanner, "patient.offline")
    }
}
