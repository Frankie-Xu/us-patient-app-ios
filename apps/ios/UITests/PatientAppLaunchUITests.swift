import XCTest

@MainActor
final class PatientAppLaunchUITests: XCTestCase {
    func testDeterministicSignedInImportAndReviewPath() {
        let app = XCUIApplication()
        app.launchArguments = ["--patient-app-demo-signed-in"]
        app.launch()

        let homeImport = app.buttons["Import synthetic record"]
        XCTAssertTrue(homeImport.waitForExistence(timeout: 8), "Home should expose the deterministic import action")
        homeImport.tap()

        let reviewTab = app.tabBars.buttons["Review"]
        XCTAssertTrue(reviewTab.waitForExistence(timeout: 5), "Review tab should be exposed to UI automation")
        reviewTab.tap()

        XCTAssertTrue(app.navigationBars["Review"].waitForExistence(timeout: 8), "Review screen should be reachable after import")

        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "deterministic-review-path"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testSignedOutLaunchShowsAccessibleSignInControls() {
        let app = XCUIApplication()
        app.launchArguments = ["--patient-app-deterministic-client"]
        app.launch()

        XCTAssertTrue(app.textFields["patient.login.identifier"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.buttons["patient.login.submit"].exists)
    }

    func testConfirmedFactsReachVisitQuestionsAndShare() {
        let app = XCUIApplication()
        app.launchArguments = ["--patient-app-demo-signed-in"]
        app.launch()

        let importRecord = app.buttons["Import synthetic record"]
        XCTAssertTrue(importRecord.waitForExistence(timeout: 8))
        importRecord.tap()

        let review = app.tabBars.buttons["Review"]
        XCTAssertTrue(review.waitForExistence(timeout: 8))
        review.tap()

        let confirm = app.buttons["Confirm reviewed fact"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 8))
        XCTAssertTrue(confirm.isEnabled)
        confirm.tap()

        let prepareVisit = app.buttons["Prepare doctor visit"]
        XCTAssertTrue(prepareVisit.waitForExistence(timeout: 8))
        XCTAssertTrue(prepareVisit.isEnabled)
        prepareVisit.tap()

        XCTAssertTrue(app.navigationBars["Doctor brief"].waitForExistence(timeout: 8))
        let questions = app.buttons["Continue to visit questions"]
        XCTAssertTrue(questions.waitForExistence(timeout: 8))
        questions.tap()
        XCTAssertTrue(app.navigationBars["Visit questions"].waitForExistence(timeout: 8))

        let shareRecord = app.buttons["Export and share record"]
        XCTAssertTrue(shareRecord.waitForExistence(timeout: 8))
        shareRecord.tap()
        XCTAssertTrue(app.navigationBars["Share record"].waitForExistence(timeout: 8))
        let pdf = app.buttons["Export PDF"]
        XCTAssertTrue(pdf.waitForExistence(timeout: 8))
        pdf.tap()
        XCTAssertTrue(app.staticTexts["PDF v1 ready"].waitForExistence(timeout: 8))

        let createShare = app.buttons["Create 24-hour share"]
        XCTAssertTrue(createShare.waitForExistence(timeout: 8))
        createShare.tap()
        XCTAssertTrue(app.buttons["Revoke share"].waitForExistence(timeout: 8))
        app.buttons["Revoke share"].tap()
        XCTAssertTrue(app.staticTexts["Share revoked"].waitForExistence(timeout: 8))
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "deterministic-share-revoked"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }
}
