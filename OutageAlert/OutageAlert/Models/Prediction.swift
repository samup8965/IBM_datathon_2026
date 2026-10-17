import Foundation

enum RiskLevel: String, Codable, CaseIterable {
    case low, moderate, severe, critical
    var title: String { rawValue.capitalized }
    var needsAttention: Bool { self == .severe || self == .critical }
    var statusMessage: String {
        switch self {
        case .low: "Grid conditions currently appear stable."
        case .moderate: "Grid pressure is rising. A little preparation now can help."
        case .severe: "Grid conditions are deteriorating. Prepare essential backup power."
        case .critical: "Outage risk is critical. Prepare for possible imminent power loss."
        }
    }
    func recommendations(for profile: UserProfile) -> [String] {
        switch (profile, self) {
        case (.household, .low):
            ["No urgent action needed", "Keep devices normally charged"]
        case (.household, .moderate):
            ["Consider charging phone and laptop", "Charge power bank", "Save important work"]
        case (.household, .severe):
            ["Charge essential devices now", "Prepare backup lighting", "Save computer work", "Minimise opening refrigerator/freezer"]
        case (.household, .critical):
            ["Prepare for imminent outage", "Fully charge essential devices", "Ensure power banks are ready", "Prepare backup lighting", "Protect refrigerated essentials", "Save all important work immediately"]
        case (.medical, .low):
            ["Ensure backup battery is available"]
        case (.medical, .moderate):
            ["Begin charging backup battery", "Check backup power source"]
        case (.medical, .severe):
            ["Fully charge medical equipment backup", "Confirm alternative power source", "Notify caregiver/support person if needed"]
        case (.medical, .critical):
            ["Prepare for possible imminent power loss", "Switch or prepare backup power immediately", "Confirm remaining battery duration", "Contact caregiver/support if backup time may be insufficient"]
        }
    }
}

enum UserProfile: String, CaseIterable, Identifiable {
    case household, medical
    var id: String { rawValue }
    var title: String { self == .household ? "Household" : "Medical Power Dependency" }
    var symbol: String { self == .household ? "house.fill" : "cross.case.fill" }
}

/// SwiftUI-independent wire model. Use JSONDecoder with .iso8601 dates for future API JSON.
struct Prediction: Codable {
    let location: String
    let riskProbability: Double
    let riskLevel: RiskLevel
    let updatedAt: Date
    let gridStability: String
    let electricityDemand: String
    let weatherRisk: String
    var percentage: Int { Int((riskProbability * 100).rounded()) }
    enum CodingKeys: String, CodingKey {
        case location
        case riskProbability = "risk_probability"
        case riskLevel = "risk_level"
        case updatedAt = "updated_at"
        case gridStability = "grid_stability"
        case electricityDemand = "electricity_demand"
        case weatherRisk = "weather_risk"
    }
}
