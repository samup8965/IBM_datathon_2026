import Foundation

/// Replace with a LinuxONE service when ready; no networking is implemented here.
@MainActor
protocol PredictionProviding {
    func fetchPrediction() async throws -> Prediction
}

/// Demo controls remain separate from the future API contract.
@MainActor
protocol DemoControlling: AnyObject {
    var step: Int { get }
    var stepCount: Int { get }
    func advance()
    func reset()
}

@MainActor
final class MockPredictionProvider: PredictionProviding, DemoControlling {
    private(set) var step = 0
    let stepCount = RiskLevel.allCases.count
    private let now: () -> Date
    init(now: @escaping () -> Date = Date.init) { self.now = now }
    func advance() { step = min(step + 1, stepCount - 1) }
    func reset() { step = 0 }
    func fetchPrediction() async throws -> Prediction { currentPrediction() }
    func currentPrediction() -> Prediction {
        let probabilities = [0.12, 0.34, 0.68, 0.89]
        let stability = ["Stable", "Fluctuating", "Unstable", "Highly unstable"]
        let demand = ["Normal", "Elevated", "High", "Peak load"]
        return Prediction(location: "Caracas, Venezuela", riskProbability: probabilities[step],
                          riskLevel: RiskLevel.allCases[step], updatedAt: now(),
                          gridStability: stability[step], electricityDemand: demand[step],
                          weatherRisk: RiskLevel.allCases[step].title)
    }
}
