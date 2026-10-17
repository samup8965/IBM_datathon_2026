import SwiftUI

struct ContentView: View {
    @State private var model: DashboardModel
    @State private var showingMap = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    init() { _model = State(initialValue: DashboardModel.makeDemo()) }
    init(model: DashboardModel) { _model = State(initialValue: model) }
    private var risk: RiskLevel { model.prediction.riskLevel }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                header
                profileSelector
                riskCard
                gridConditions
                readinessCard
                if let error = model.errorMessage {
                    Text(error).font(.footnote).foregroundStyle(.red)
                }
                Text("IBM Z DATATHON  ·  OUTAGE ALERT")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .tracking(1.5).foregroundStyle(DashboardStyle.secondary).padding(.vertical, 8)
            }
            .padding(.horizontal, 20).padding(.top, 12).padding(.bottom, 16)
            .frame(maxWidth: 560).frame(maxWidth: .infinity)
        }
        .clipped()
        .background(DashboardStyle.background)
        .safeAreaInset(edge: .bottom, spacing: 0) { if model.isDemo { demoControls } }
        .foregroundStyle(DashboardStyle.ink)
        .preferredColorScheme(.light)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.35), value: risk)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.25), value: model.profile)
        .fullScreenCover(isPresented: $showingMap) { RegionalMapView(model: model) }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(systemName: "bolt.shield.fill").font(.title3).foregroundStyle(.white)
                .frame(width: 42, height: 42)
                .background(DashboardStyle.ink, in: RoundedRectangle(cornerRadius: 13))
            VStack(alignment: .leading, spacing: 3) {
                Text("Outage Alert").font(.headline)
                Label(model.prediction.location, systemImage: "location.fill")
                    .font(.caption).foregroundStyle(DashboardStyle.secondary)
            }
            Spacer(minLength: 0)
            Button { showingMap = true } label: {
                Label("Map", systemImage: "map")
                    .font(.system(size: 12, weight: .semibold))
                    .padding(.horizontal, 12).frame(minHeight: 44)
                    .background(.white, in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("open-map")
        }.padding(.bottom, 4)
    }

    private var riskCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Power Outage Risk").font(.title2.weight(.bold))
                    Text("Next 30 minutes").font(.subheadline).foregroundStyle(DashboardStyle.secondary)
                }
                Spacer()
                Image(systemName: risk.symbol).font(.title2).foregroundStyle(risk.color)
                    .padding(10).background(risk.color.opacity(0.08), in: Circle()).accessibilityHidden(true)
            }
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline, spacing: 2) {
                    Text("\(model.prediction.percentage)")
                        .font(.system(size: 72, weight: .semibold, design: .rounded))
                        .tracking(-4).monospacedDigit().contentTransition(.numericText())
                    Text("%").font(.system(size: 38, weight: .medium, design: .rounded))
                }
                Text(risk.title.uppercased()).font(.system(size: 13, weight: .heavy)).tracking(2)
                    .padding(.horizontal, 12).padding(.vertical, 6)
                    .background(risk.color.opacity(0.09), in: Capsule())
            }
            .foregroundStyle(risk.color)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Outage risk \(model.prediction.percentage) percent, \(risk.title), next 30 minutes")
            .accessibilityIdentifier("risk-summary")

            HStack(spacing: 5) {
                ForEach(RiskLevel.allCases, id: \.self) { level in
                    VStack(spacing: 7) {
                        Capsule().fill(level == risk ? level.color : level.color.opacity(0.16)).frame(height: 5)
                        Text(level.title).font(.system(size: 10, weight: level == risk ? .bold : .medium))
                            .foregroundStyle(level == risk ? level.color : DashboardStyle.secondary)
                    }.frame(maxWidth: .infinity)
                }
            }.accessibilityHidden(true)
            Text(risk.statusMessage).font(.subheadline).lineSpacing(3).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 5) {
                Image(systemName: "clock")
                Text("Updated \(model.prediction.updatedAt.formatted(date: .omitted, time: .standard))")
                if model.isDemo { Text("· Demo data") }
            }.font(.caption2).foregroundStyle(DashboardStyle.secondary)
        }
        .modifier(DashboardCard())
        .overlay(alignment: .top) {
            Capsule().fill(risk.color).frame(height: 4).padding(.horizontal, 24).accessibilityHidden(true)
        }
    }

    private var gridConditions: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Live Grid Conditions").font(.headline)
                Spacer()
                Text(model.isDemo ? "SIMULATED" : "CURRENT")
                    .font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(DashboardStyle.secondary)
            }
            gridRow("Grid Stability", value: model.prediction.gridStability, symbol: "waveform.path.ecg")
            gridRow("Electricity Demand", value: model.prediction.electricityDemand, symbol: "bolt.fill")
            gridRow("Weather Risk", value: model.prediction.weatherRisk, symbol: "cloud.sun.fill")
        }.modifier(DashboardCard())
    }
    private func gridRow(_ title: String, value: String, symbol: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol).frame(width: 20).foregroundStyle(DashboardStyle.secondary)
            Text(title).foregroundStyle(DashboardStyle.secondary)
            Spacer(minLength: 8)
            Text(value).fontWeight(.semibold).foregroundStyle(risk.color)
        }.font(.subheadline).accessibilityElement(children: .combine)
    }

    private var profileSelector: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("YOUR PROFILE").font(.system(size: 10, weight: .bold)).tracking(1.5).foregroundStyle(DashboardStyle.secondary)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 6) { profileButtons }
                VStack(spacing: 6) { profileButtons }
            }
            .padding(5).background(DashboardStyle.ink.opacity(0.05), in: RoundedRectangle(cornerRadius: 17))
        }.padding(.vertical, 4)
    }
    @ViewBuilder private var profileButtons: some View {
        ForEach(UserProfile.allCases) { profile in
            Button { model.profile = profile } label: {
                Label(profile.title, systemImage: profile.symbol)
                    .font(.system(size: 12, weight: .semibold)).fixedSize(horizontal: true, vertical: false)
                    .frame(maxWidth: .infinity, minHeight: 44).padding(.horizontal, 8)
                    .foregroundStyle(model.profile == profile ? .white : DashboardStyle.secondary)
                    .background(model.profile == profile ? DashboardStyle.ink : .clear, in: RoundedRectangle(cornerRadius: 12))
            }
            .buttonStyle(.plain)
            .accessibilityAddTraits(model.profile == profile ? .isSelected : [])
            .accessibilityIdentifier("profile-\(profile.rawValue)")
        }
    }

    private var readinessCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(model.profile == .medical ? "Medical Power Readiness" : "Recommended Actions", systemImage: model.profile.symbol)
                .font(.headline)
            if model.profile == .medical {
                medicalEquipment
                if risk.needsAttention {
                    VStack(alignment: .leading, spacing: 7) {
                        Label(risk == .critical ? "Prepare backup power immediately" : "Prioritise medical backup power", systemImage: "exclamationmark.triangle.fill")
                            .font(.subheadline.weight(.bold))
                        Text("Confirm your backup plan and contact your support person if needed.").font(.caption).lineSpacing(2)
                    }
                    .foregroundStyle(risk == .critical ? .white : risk.color)
                    .padding(14).frame(maxWidth: .infinity, alignment: .leading)
                    .background(risk == .critical ? risk.color : risk.color.opacity(0.09), in: RoundedRectangle(cornerRadius: 14))
                    .accessibilityIdentifier("medical-warning")
                }
            }
            VStack(alignment: .leading, spacing: 14) {
                ForEach(Array(risk.recommendations(for: model.profile).enumerated()), id: \.element) { index, action in
                    HStack(alignment: .top, spacing: 12) {
                        Text("\(index + 1)").font(.system(size: 11, weight: .bold, design: .rounded))
                            .frame(width: 23, height: 23).foregroundStyle(risk.color)
                            .background(risk.color.opacity(0.08), in: Circle())
                        Text(action).font(.subheadline).lineSpacing(2)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 2)
                    }
                }
            }
            if model.profile == .medical {
                Text("Preparedness guidance only. Follow your equipment instructions and personal care plan. This is not a medical diagnosis tool.")
                    .font(.caption2).foregroundStyle(DashboardStyle.secondary).lineSpacing(3)
            }
        }
        .modifier(DashboardCard())
        .overlay {
            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(model.profile == .medical && risk.needsAttention ? risk.color.opacity(0.5) : .clear, lineWidth: 1.5)
        }
    }
    private var medicalEquipment: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("EXAMPLE DEVICE").font(.system(size: 9, weight: .bold)).tracking(1).foregroundStyle(DashboardStyle.secondary)
                    Text("Oxygen Concentrator").font(.subheadline.weight(.semibold))
                }
                Spacer()
                Image(systemName: "lungs.fill").font(.title2).foregroundStyle(DashboardStyle.secondary)
            }
            Divider()
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "battery.50percent")
                VStack(alignment: .leading, spacing: 3) {
                    Text("42 minutes remaining").font(.subheadline.weight(.bold))
                    Text("Backup battery · demo estimate").font(.caption2).foregroundStyle(DashboardStyle.secondary)
                }
            }.foregroundStyle(risk.needsAttention ? risk.color : DashboardStyle.ink)
        }.padding(14).background(DashboardStyle.background, in: RoundedRectangle(cornerRadius: 14))
    }

    private var demoControls: some View {
        VStack(spacing: 10) {
            HStack {
                Label("DEMO SIMULATION", systemImage: "slider.horizontal.3").font(.system(size: 9, weight: .bold)).tracking(1)
                Spacer()
                HStack(spacing: 4) {
                    ForEach(0..<4) { index in
                        Capsule().fill(index <= model.demoStep ? risk.color : DashboardStyle.ink.opacity(0.12)).frame(width: 15, height: 4)
                    }
                }.accessibilityLabel("Simulation step \(model.demoStep + 1) of 4")
                Button("Reset") { Task { await model.resetDemo() } }
                    .font(.caption.weight(.semibold)).padding(.leading, 8).frame(minWidth: 44, minHeight: 28)
                    .disabled(model.isLoading).accessibilityIdentifier("reset-demo")
            }.foregroundStyle(DashboardStyle.secondary)
            Button { Task { await model.advanceDemo() } } label: {
                HStack(spacing: 10) {
                    Image(systemName: model.isFinalStep ? "checkmark.circle" : "waveform.path.ecg")
                    Text(model.isFinalStep ? "Critical reached · Reset to replay" : "Simulate Grid Deterioration").font(.subheadline.weight(.semibold))
                    Spacer(minLength: 0)
                    if !model.isFinalStep { Image(systemName: "arrow.right") }
                }
                .padding(.horizontal, 17).frame(minHeight: 50).foregroundStyle(.white)
                .background(model.isFinalStep ? risk.color : DashboardStyle.ink, in: RoundedRectangle(cornerRadius: 15))
            }
            .buttonStyle(.plain).disabled(model.isLoading || model.isFinalStep).accessibilityIdentifier("advance-demo")
        }
        .padding(.horizontal, 20).padding(.top, 10).padding(.bottom, 8)
        .frame(maxWidth: 560).frame(maxWidth: .infinity).background(.regularMaterial)
        .overlay(alignment: .top) { Divider() }
    }
}

#Preview("Household · Low") { ContentView() }
#Preview("Medical · Critical") { ContentView(model: .makeDemo(step: 3, profile: .medical)) }
