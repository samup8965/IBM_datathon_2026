import SwiftUI

struct RegionalMapView: View {
    let model: DashboardModel
    @Environment(\.dismiss) private var dismiss
    @State private var regions: [ADM1Region] = []
    @State private var selectedID = "VE-A"
    @State private var loadFailed = false
    private let provider = MockRegionalPredictionProvider()

    private var predictions: [String: RegionalPrediction] {
        guard model.isDemo else { return [:] }
        return Dictionary(uniqueKeysWithValues: regions.compactMap { region in
            provider.prediction(for: region.id, demoStep: model.demoStep).map { (region.id, $0) }
        })
    }
    private var selectedRegion: ADM1Region? { regions.first { $0.id == selectedID } }

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Venezuela").font(.title2.weight(.bold))
                    Text("ADM1 regions").font(.caption).foregroundStyle(DashboardStyle.secondary)
                }
                Spacer(minLength: 12)
                Button { dismiss() } label: {
                    Label("Current location", systemImage: "location.fill")
                        .font(.system(size: 12, weight: .semibold))
                        .padding(.horizontal, 12).frame(minHeight: 44)
                        .background(.white, in: Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityHint("Return to the Caracas demo dashboard")
                .accessibilityIdentifier("return-current-location")
            }
            .padding(.horizontal, 20).padding(.top, 12).padding(.bottom, 16)
            .frame(maxWidth: 600)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Regional outage risk").font(.headline)
                            Text("Next 30 minutes · \(model.isDemo ? "Demo predictions" : "No regional predictions")")
                                .font(.caption).foregroundStyle(DashboardStyle.secondary)
                        }
                        Spacer()
                        Text("\(regions.count) REGIONS").font(.system(size: 9, weight: .bold, design: .monospaced))
                            .foregroundStyle(DashboardStyle.secondary)
                    }
                    if loadFailed {
                        ContentUnavailableView("Map unavailable", systemImage: "map", description: Text("The bundled boundaries could not be loaded. Return to Current location to continue the demo."))
                    } else if regions.isEmpty {
                        ProgressView("Loading regions…").frame(maxWidth: .infinity, minHeight: 300)
                    } else {
                        VenezuelaMapCanvas(regions: regions, predictions: predictions, selectedID: $selectedID)
                            .aspectRatio(1.08, contentMode: .fit)
                        legend
                        regionSelector
                        if let region = selectedRegion { regionDetails(region) }
                        Text("Tap a region to explore. Pinch to zoom, then drag to pan. Small islands and coastal regions are also available in the selector.")
                            .font(.caption).foregroundStyle(DashboardStyle.secondary).lineSpacing(3)
                        VStack(alignment: .leading, spacing: 5) {
                            Text("Boundaries: OCHA / INE via geoBoundaries · 2020")
                            Link("CC BY 3.0 IGO · Source & attribution", destination: URL(string: "https://www.geoboundaries.org/api/current/gbOpen/VEN/ADM1/")!)
                        }
                        .font(.system(size: 10)).foregroundStyle(DashboardStyle.secondary)
                    }
                }
                .padding(.horizontal, 20).padding(.bottom, 24)
                .frame(maxWidth: 600).frame(maxWidth: .infinity)
            }.clipped()
        }
        .frame(maxWidth: .infinity)
        .background(DashboardStyle.background)
        .foregroundStyle(DashboardStyle.ink)
        .preferredColorScheme(.light)
        .task {
            do { regions = try ADM1BoundaryLoader.load() }
            catch { loadFailed = true }
        }
    }

    private var legend: some View {
        HStack(spacing: 0) {
            ForEach(RiskLevel.allCases, id: \.self) { level in
                HStack(spacing: 5) {
                    Circle().fill(level.color).frame(width: 7, height: 7)
                    Text(level.title).font(.system(size: 11, weight: .medium))
                }.frame(maxWidth: .infinity)
            }
        }
        .accessibilityElement(children: .combine)
    }
    private var regionSelector: some View {
        Menu {
            ForEach(regions) { region in
                Button { selectedID = region.id } label: {
                    if region.id == selectedID { Label(region.name, systemImage: "checkmark") }
                    else { Text(region.name) }
                }.accessibilityIdentifier("select-region-\(region.id)")
            }
        } label: {
            HStack {
                Image(systemName: "map")
                Text(selectedRegion?.name ?? "Select a region").fontWeight(.semibold)
                Spacer()
                Image(systemName: "chevron.up.chevron.down").font(.caption.weight(.semibold))
            }
            .font(.subheadline).padding(.horizontal, 16).frame(minHeight: 48)
            .background(.white, in: RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Select region, \(selectedRegion?.name ?? "none")")
        .accessibilityIdentifier("map-region-selector")
    }
    private func regionDetails(_ region: ADM1Region) -> some View {
        HStack(alignment: .center, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(region.name).font(.headline)
                Text(region.id == "VE-A" ? "Caracas · current demo location" : "Regional demo prediction")
                    .font(.caption).foregroundStyle(DashboardStyle.secondary)
                Text("ADM1 · \(region.id)").font(.system(size: 10, weight: .medium, design: .monospaced)).foregroundStyle(DashboardStyle.secondary)
            }
            Spacer(minLength: 0)
            if let prediction = predictions[region.id] {
                VStack(alignment: .trailing, spacing: 2) {
                    Text("\(prediction.percentage)%").font(.system(size: 32, weight: .semibold, design: .rounded)).monospacedDigit()
                    Text(prediction.level.title.uppercased()).font(.system(size: 10, weight: .bold)).tracking(1)
                }.foregroundStyle(prediction.level.color)
            } else {
                Text("No data").font(.subheadline).foregroundStyle(DashboardStyle.secondary)
            }
        }
        .modifier(DashboardCard())
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("map-region-detail")
    }
}

#Preview { RegionalMapView(model: .makeDemo()) }
