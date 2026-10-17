import Foundation
import Observation

@MainActor @Observable
final class DashboardModel {
    private(set) var prediction: Prediction
    var profile: UserProfile = .household
    private(set) var isLoading = false
    private(set) var errorMessage: String?
    private(set) var demoStep: Int
    @ObservationIgnored private let provider: any PredictionProviding
    @ObservationIgnored private let demo: (any DemoControlling)?
    var isDemo: Bool { demo != nil }
    var isFinalStep: Bool { demoStep >= (demo?.stepCount ?? 1) - 1 }

    init(provider: any PredictionProviding, initialPrediction: Prediction, demo: (any DemoControlling)? = nil) {
        self.provider = provider
        self.prediction = initialPrediction
        self.demo = demo
        self.demoStep = demo?.step ?? 0
    }
    static func makeDemo(step: Int = 0, profile: UserProfile = .household) -> DashboardModel {
        let provider = MockPredictionProvider()
        for _ in 0..<max(0, min(step, provider.stepCount - 1)) { provider.advance() }
        let model = DashboardModel(provider: provider, initialPrediction: provider.currentPrediction(), demo: provider)
        model.profile = profile
        return model
    }
    func advanceDemo() async {
        guard let demo, !isLoading, !isFinalStep else { return }
        demo.advance()
        await refresh()
    }
    func resetDemo() async {
        guard let demo, !isLoading else { return }
        demo.reset()
        await refresh()
    }
    func refresh() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            prediction = try await provider.fetchPrediction()
            demoStep = demo?.step ?? 0
            errorMessage = nil
        } catch {
            errorMessage = "Unable to update. Showing the last available prediction."
        }
    }
}
