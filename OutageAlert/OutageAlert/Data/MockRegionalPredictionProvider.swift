import Foundation

struct RegionalPrediction {
    let regionID: String
    let percentage: Int
    let level: RiskLevel
}

/// Deliberately fictional spatial variation for the demo. No geographic inference.
/// Replace this lookup with backend predictions keyed to the agreed ADM1 region IDs.
struct MockRegionalPredictionProvider {
    private let offsets: [String: Int] = [
        "VE-A": 0, "VE-B": 1, "VE-C": 0, "VE-D": 1, "VE-E": 0,
        "VE-F": 1, "VE-G": 2, "VE-H": 0, "VE-I": 1, "VE-J": 0,
        "VE-K": 1, "VE-L": 0, "VE-M": 1, "VE-N": 0, "VE-O": 0,
        "VE-P": 1, "VE-R": 1, "VE-S": 0, "VE-T": 0, "VE-U": 1,
        "VE-V": 2, "VE-W": 0, "VE-X": 0, "VE-Y": 0, "VE-Z": 0
    ]

    func prediction(for regionID: String, demoStep: Int) -> RegionalPrediction? {
        guard let offset = offsets[regionID] else { return nil }
        let step = min(3, max(0, demoStep) + offset)
        return RegionalPrediction(regionID: regionID, percentage: [12, 34, 68, 89][step], level: RiskLevel.allCases[step])
    }
}
