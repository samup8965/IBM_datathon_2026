import Foundation

@MainActor
private struct UnavailableProvider: PredictionProviding {
    func fetchPrediction() async throws -> Prediction { throw URLError(.notConnectedToInternet) }
}

@main
struct DemoChecks {
    @MainActor static func main() async throws {
        let model = DashboardModel.makeDemo()
        let percentages = [12, 34, 68, 89]
        var previousStability = ""
        for (index, risk) in RiskLevel.allCases.enumerated() {
            precondition(model.prediction.percentage == percentages[index])
            precondition(model.prediction.riskLevel == risk)
            precondition(model.demoStep == index)
            precondition(model.prediction.gridStability != previousStability)
            previousStability = model.prediction.gridStability
            for profile in UserProfile.allCases {
                model.profile = profile
                precondition(!risk.recommendations(for: profile).isEmpty)
                precondition(model.prediction.riskLevel == risk, "Switching profile must preserve the risk")
            }
            await model.advanceDemo()
        }
        precondition(model.isFinalStep)
        precondition(model.prediction.percentage == 89, "Critical must not wrap silently")
        await model.resetDemo()
        precondition(model.prediction.percentage == 12 && model.demoStep == 0)
        precondition(model.profile == .medical, "Reset must preserve the chosen profile")
        let failing = DashboardModel(provider: UnavailableProvider(), initialPrediction: model.prediction)
        await failing.refresh()
        precondition(failing.errorMessage != nil && !failing.isLoading)
        precondition(failing.prediction.percentage == 12 && !failing.isDemo)
        let json = #"{"location":"Caracas","risk_probability":0.89,"risk_level":"critical","updated_at":"2026-10-17T19:00:00Z","grid_stability":"Unstable","electricity_demand":"High","weather_risk":"Severe"}"#
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let prediction = try decoder.decode(Prediction.self, from: Data(json.utf8))
        precondition(prediction.percentage == 89 && prediction.riskLevel == .critical)
        let boundaryData = try Data(contentsOf: URL(fileURLWithPath: "OutageAlert/Resources/venezuela-adm1.geojson"))
        let regions = try ADM1BoundaryLoader.decode(boundaryData)
        precondition(regions.count == 25 && Set(regions.map(\.id)).count == 25)
        precondition(regions.first(where: { $0.id == "VE-A" })?.name == "Distrito Capital")
        precondition((regions.first(where: { $0.id == "VE-W" })?.polygons.count ?? 0) > 1)
        let regionalProvider = MockRegionalPredictionProvider()
        for step in 0..<4 {
            for region in regions {
                let value = regionalProvider.prediction(for: region.id, demoStep: step)
                precondition(value != nil && value?.regionID == region.id)
            }
            precondition(regionalProvider.prediction(for: "VE-A", demoStep: step)?.percentage == percentages[step])
        }
        precondition(regionalProvider.prediction(for: "unknown", demoStep: 0) == nil)
        do {
            _ = try ADM1BoundaryLoader.decode(Data("{\"type\":\"FeatureCollection\",\"features\":[]}".utf8))
            preconditionFailure("Empty boundary collections must fail")
        } catch { }
        print("PASS: demo sequence, profiles, reset, provider failure, JSON decoding, 25 ADM1 geometries, islands, and regional risk joins")
    }
}
