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

    func testEveryStatusHasLocalizedVoiceOverCopyAndStableIdentifier() {
        let locales = [Locale(identifier: "en_US"), Locale(identifier: "zh-Hans")]
        let hintKeys = [
            "status.loading.hint",
            "status.failure.hint",
            "status.offline.hint",
            "status.success.hint"
        ]

        for state in PatientStatusState.allCases {
            XCTAssertTrue(state.accessibilityIdentifier.hasPrefix("patient.status."))
            XCTAssertFalse(state.systemImage.isEmpty)
            for locale in locales {
                XCTAssertFalse(PatientLocalization.localized(state.localizationKey, locale: locale).isEmpty)
            }
        }

        for key in hintKeys {
            for locale in locales {
                let copy = PatientLocalization.localized(key, locale: locale)
                XCTAssertFalse(copy.isEmpty)
                XCTAssertNotEqual(copy, key)
            }
        }
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
