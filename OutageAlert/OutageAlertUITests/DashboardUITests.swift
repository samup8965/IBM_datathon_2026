import XCTest

final class DashboardUITests: XCTestCase {
    @MainActor
    func testADM1MapNavigationAndSelection() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.buttons["open-map"].waitForExistence(timeout: 10))
        app.buttons["profile-medical"].tap()
        app.buttons["advance-demo"].tap()
        let risk = app.descendants(matching: .any)["risk-summary"].firstMatch
        let moderate = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "34 percent, Moderate"), object: risk)
        XCTAssertEqual(XCTWaiter.wait(for: [moderate], timeout: 5), .completed)
        app.buttons["open-map"].tap()
        let back = app.buttons["return-current-location"]
        XCTAssertTrue(back.waitForExistence(timeout: 5))
        let map = app.descendants(matching: .any)["adm1-map-canvas"].firstMatch
        XCTAssertTrue(map.waitForExistence(timeout: 5))
        let detail = app.descendants(matching: .any)["map-region-detail"].firstMatch
        XCTAssertTrue(detail.label.contains("Distrito Capital"))
        XCTAssertTrue(detail.label.contains("34%"))
        capture("Venezuela-ADM1-Map")
        // Tap inside Zulia's mainland polygon, not a list row.
        map.coordinate(withNormalizedOffset: CGVector(dx: 0.15, dy: 0.25)).tap()
        XCTAssertTrue(detail.label.contains("Zulia"))
        XCTAssertTrue(detail.label.contains("89%"))
        app.buttons["map-zoom-in"].tap()
        XCTAssertTrue(app.buttons["map-zoom-out"].isEnabled)
        app.buttons["map-fit"].tap()
        XCTAssertFalse(app.buttons["map-zoom-out"].isEnabled)
        app.buttons["map-region-selector"].tap()
        app.buttons["select-region-VE-Z"].tap()
        XCTAssertTrue(detail.label.contains("Amazonas"))
        capture("Venezuela-ADM1-Selection")
        back.tap()
        XCTAssertTrue(app.buttons["open-map"].waitForExistence(timeout: 5))
        XCTAssertTrue(risk.label.contains("34 percent, Moderate"))
        XCTAssertTrue(app.buttons["profile-medical"].isSelected)
        app.buttons["open-map"].tap()
        XCTAssertTrue(back.waitForExistence(timeout: 5))
        XCTAssertTrue(detail.label.contains("Distrito Capital"))
        back.tap()
    }

    @MainActor
    func testRecordedDemoFlow() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        let risk = app.descendants(matching: .any)["risk-summary"].firstMatch
        XCTAssertTrue(risk.waitForExistence(timeout: 10))
        XCTAssertTrue(risk.label.contains("12 percent, Low"))
        capture("Household-Low")
        let advance = app.buttons["advance-demo"]
        for expected in ["34 percent, Moderate", "68 percent, Severe", "89 percent, Critical"] {
            advance.tap()
            let updated = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", expected), object: risk)
            XCTAssertEqual(XCTWaiter.wait(for: [updated], timeout: 5), .completed)
        }
        XCTAssertFalse(advance.isEnabled)
        app.buttons["profile-medical"].tap()
        XCTAssertTrue(risk.label.contains("89 percent, Critical"))
        app.swipeUp()
        XCTAssertTrue(app.staticTexts["Medical Power Readiness"].exists)
        XCTAssertTrue(app.staticTexts["42 minutes remaining"].exists)
        XCTAssertTrue(app.staticTexts["Prepare backup power immediately"].exists)
        capture("Medical-Critical")
        app.buttons["reset-demo"].tap()
        XCTAssertFalse(app.staticTexts["Prepare backup power immediately"].exists)
        XCTAssertTrue(app.staticTexts["Ensure backup battery is available"].exists)
        app.swipeDown()
        XCTAssertTrue(risk.label.contains("12 percent, Low"))
        XCTAssertTrue(app.buttons["profile-medical"].isSelected)
        advance.tap()
        advance.tap()
        app.swipeUp()
        XCTAssertTrue(app.staticTexts["Prioritise medical backup power"].exists)
        capture("Medical-Severe")
    }

    @MainActor
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
