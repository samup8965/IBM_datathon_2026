# Outage Alert

A SwiftUI, mock-data-only IBM Z Datathon demo for electricity-outage preparedness in Caracas, Venezuela. No network calls, accounts, notifications, or backend setup are required.

## Run in Xcode

1. Open `OutageAlert.xcodeproj`.
2. Select the **OutageAlert** scheme and an **iPhone 17 Pro** simulator in the top toolbar.
3. Press **Command-R**. The project currently targets iOS 26.5 or later, matching the installed simulator.
4. Use **Simulate Grid Deterioration** to advance 12% Low → 34% Moderate → 68% Severe → 89% Critical. **Reset** returns to Low while keeping the selected profile.
5. Switch to **Medical Power Dependency** at the top. Scroll to see Medical Power Readiness, the example oxygen concentrator, and its simulated 42-minute backup estimate. Severe and Critical make the warning more prominent.

The demo button remains visible while scrolling. Critical is the final step; reset to replay. All predictions, grid indicators, and battery information are simulated. The displayed update time uses the device's local time zone and refreshes when a demo prediction is produced. The battery estimate does not count down or represent real equipment telemetry.

To preview without launching the simulator, select `ContentView.swift` and use **Editor → Canvas**. It includes Household/Low and Medical/Critical previews.

## Code layout

- `Models/Prediction.swift`: risk scale, profile-specific preparedness text, and Codable API model.
- `Data/PredictionProvider.swift`: async `PredictionProviding` boundary and deterministic mock provider. Demo controls have their own protocol.
- `DashboardModel.swift`: observable state, profile, simulation, and refresh/error handling.
- `ContentView.swift`, `Views/DashboardStyle.swift`: SwiftUI dashboard and presentation styling.

For LinuxONE integration, implement `PredictionProviding.fetchPrediction()` and inject it into `DashboardModel` with an initial prediction, omitting the demo controller. Use `JSONDecoder.dateDecodingStrategy = .iso8601` for the documented timestamp format; explicit coding keys already match the proposed snake_case JSON. Before connecting production predictions, add API validation, loading/staleness policy, and authentication as required by that service. No networking is implemented in this demo.

## Checks

- **Command-U** runs the UI demo flow: all four levels, switching to medical, urgent warnings, reset, and preservation of the profile. Screenshots are retained in the test report.
- `Tests/run-checks.sh` checks the model sequence, profile recommendations, final-step behavior, reset, failed provider handling, and future JSON decoding without requiring a simulator.

## ADM1 map

Tap **Map** in the dashboard's upper-right corner. The full-screen Venezuela map supports tapping region polygons, pinch zoom, dragging while zoomed, plus/minus zoom, and **Fit Venezuela**. Use the region selector for small coastal regions or islands. **Current location** in the upper-right corner returns to the existing Caracas dashboard and preserves its profile and demo state; it does not request GPS permission or change the location.

The map bundles public GeoJSON, so displaying and interacting with the map requires no internet connection. Attribution links open externally only when tapped. The boundary data is geoBoundaries `VEN-ADM1-42786344` (2020 boundaries, revision `9469f09`), sourced from OCHA Venezuela / Instituto Nacional de Estadística: 23 states, Distrito Capital, and Dependencias Federales. Polygon holes and all MultiPolygon parts are retained. The projection is equirectangular, adjusted for mean latitude. See `OutageAlert/Resources/BOUNDARY-LICENSE.txt` and the bundled source metadata for the CC BY 3.0 IGO attribution.

`ADM1BoundaryLoader` decodes the GeoJSON into regions identified by ISO codes (for example `VE-A` for Distrito Capital) and retains source shape IDs. These are public dataset identifiers, not a claim of an exact match to the ML training dataset. Confirm or add the model's region-code crosswalk before live integration.

`MockRegionalPredictionProvider` supplies explicitly fictional regional risks keyed by ISO code. Distrito Capital matches the dashboard's simulation step; other regions use fixed demo offsets. Unknown regions show no data, and the view does not synthesize regional predictions when the dashboard uses a non-demo provider. Selecting a region only changes the map's detail card.

The UI tests cover opening the map, selecting a polygon, zoom/fit, selecting a region from the menu, and returning with profile/risk state intact. The command-line checks also validate region IDs, island geometry, and coverage of every region at each demo step.
