import XCTest

/// Drives the real app in a simulator and captures the App Store screenshots.
///
/// Why a UI test and not a mockup: Apple requires screenshots to show the app
/// actually running ([guideline 2.3.3](https://developer.apple.com/app-store/review/guidelines/#accurate-metadata)).
/// These are captures of the shipping binary on a real screen size — the same
/// build that goes to TestFlight.
///
/// The simulator device decides the pixel size, so the CI job picks one that
/// matches the slot being filled:
///   iPhone 11 Pro Max → 1242×2688  (App Store 6.5")
///   iPhone 15 Pro Max → 1290×2796  (App Store 6.9")
///
/// Credentials come from the environment, never the source. Set them as repo
/// secrets; a run without them still captures every logged-out screen.
final class ScreenshotTests: XCTestCase {

    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launch()
    }

    /// Attach a screenshot so `xcparse` can pull it off the .xcresult afterwards.
    /// `.keepAlways` matters — Xcode deletes attachments from passing tests by
    /// default, which would throw away the entire point of this job.
    private func capture(_ name: String) {
        let shot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: shot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func wait(_ element: XCUIElement, _ seconds: TimeInterval = 20) -> Bool {
        element.waitForExistence(timeout: seconds)
    }

    func testCaptureStoreScreenshots() throws {
        // 1 — Sign-in. Worth shipping as a screenshot: it shows Sign in with
        // Apple, which is what an iOS member looks for first.
        XCTAssertTrue(wait(app.buttons["Sign in"]), "sign-in screen never appeared")
        capture("01-sign-in")

        guard let identifier = ProcessInfo.processInfo.environment["MCZ_UITEST_USER"],
              let password = ProcessInfo.processInfo.environment["MCZ_UITEST_PASSWORD"],
              !identifier.isEmpty, !password.isEmpty else {
            // Not a failure. A fork or a PR without secrets should still get the
            // logged-out shots rather than a red X.
            XCTContext.runActivity(named: "No test credentials — logged-out shots only") { _ in }
            return
        }

        app.textFields.firstMatch.tap()
        app.textFields.firstMatch.typeText(identifier)
        app.secureTextFields.firstMatch.tap()
        app.secureTextFields.firstMatch.typeText(password)
        app.buttons["Sign in"].tap()

        // 2 — The tour, if this account hasn't finished it.
        if app.navigationBars["OmviardZ"].waitForExistence(timeout: 15) {
            capture("02-omviardz-tour")
            app.buttons["Skip"].tap()
        }

        // 3 — PersonaZ: the real catalog, 11 personas.
        XCTAssertTrue(wait(app.tabBars.buttons["PersonaZ"]), "never reached the tabs")
        app.tabBars.buttons["PersonaZ"].tap()
        XCTAssertTrue(wait(app.navigationBars["PersonaZ"]))
        // Let the list finish loading — a screenshot of a spinner is worthless.
        _ = app.cells.firstMatch.waitForExistence(timeout: 20)
        capture("03-personaz")

        // 4 — A persona's skills, which is the detail that sells the app.
        if app.cells.firstMatch.exists {
            app.cells.firstMatch.tap()
            _ = app.cells.firstMatch.waitForExistence(timeout: 10)
            capture("04-skills")
            app.navigationBars.buttons.firstMatch.tap()
        }

        // 5 — BodieZ: equipment toggles driving the exercise library.
        app.tabBars.buttons["BodieZ"].tap()
        XCTAssertTrue(wait(app.navigationBars["BodieZ"]))
        _ = app.cells.firstMatch.waitForExistence(timeout: 20)
        capture("05-bodiez")

        // 6 — Account.
        app.tabBars.buttons["Account"].tap()
        XCTAssertTrue(wait(app.navigationBars["Account"]))
        capture("06-account")
    }
}
