import SwiftUI

enum DashboardStyle {
    static let ink = Color(red: 0.09, green: 0.16, blue: 0.23)
    static let secondary = Color(red: 0.36, green: 0.41, blue: 0.47)
    static let background = Color(red: 0.95, green: 0.96, blue: 0.97)
}

extension RiskLevel {
    var color: Color {
        switch self {
        case .low: Color(red: 0.04, green: 0.43, blue: 0.34)
        case .moderate: Color(red: 0.55, green: 0.36, blue: 0.02)
        case .severe: Color(red: 0.73, green: 0.27, blue: 0.07)
        case .critical: Color(red: 0.72, green: 0.12, blue: 0.20)
        }
    }
    var symbol: String {
        switch self {
        case .low: "checkmark.shield.fill"
        case .moderate: "bolt.shield.fill"
        case .severe: "exclamationmark.triangle.fill"
        case .critical: "exclamationmark.octagon.fill"
        }
    }
}

struct DashboardCard: ViewModifier {
    func body(content: Content) -> some View {
        content.padding(20).frame(maxWidth: .infinity, alignment: .leading)
            .background(.white, in: RoundedRectangle(cornerRadius: 24))
            .overlay(RoundedRectangle(cornerRadius: 24).strokeBorder(DashboardStyle.ink.opacity(0.06)))
    }
}
