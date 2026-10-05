import XCTest
@testable import PatientAppUI

final class AccessibilityLocalizationTests: XCTestCase {
    func testAllAccessibleStatesHaveStablePresentation() {
        let states: [PatientStatusState] = [.loading, .failure, .empty, .offline, .retry, .success]
        XCTAssertEqual(states.count, PatientStatusState.allCases.count)
        XCTAssertTrue(states.allSatisfy { !$0.systemImage.isEmpty })
    }

    func testEnglishAndSimplifiedChineseResourcesShip() {
        XCTAssertTrue(PatientLocalization.hasResource("en"))
        XCTAssertTrue(PatientLocalization.hasResource("zh-Hans"))

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
        XCTAssertEqual(PatientAccessibilityIdentifier.uploadProgress, "patient.upload.progress")
        XCTAssertEqual(PatientAccessibilityIdentifier.tabHome, "patient.tab.home")
        XCTAssertEqual(PatientAccessibilityIdentifier.tabRecords, "patient.tab.records")
        XCTAssertEqual(PatientAccessibilityIdentifier.tabReview, "patient.tab.review")
        XCTAssertEqual(PatientAccessibilityIdentifier.tabVisits, "patient.tab.visits")
        XCTAssertEqual(PatientAccessibilityIdentifier.tabTasks, "patient.tab.tasks")
        XCTAssertEqual(PatientAccessibilityIdentifier.tabAccount, "patient.tab.account")
        XCTAssertEqual(PatientAccessibilityIdentifier.retry, "patient.retry")
        XCTAssertEqual(PatientAccessibilityIdentifier.offlineBanner, "patient.offline")
    }
}
