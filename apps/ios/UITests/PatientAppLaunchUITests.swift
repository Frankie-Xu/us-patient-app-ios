import XCTest

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
}
