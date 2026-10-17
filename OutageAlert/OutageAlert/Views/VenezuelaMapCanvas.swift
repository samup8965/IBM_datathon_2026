import SwiftUI

/// A bundled vector map: no map tiles, location permission, or network required.
struct VenezuelaMapCanvas: View {
    let regions: [ADM1Region]
    let predictions: [String: RegionalPrediction]
    @Binding var selectedID: String
    @State private var zoom: CGFloat = 1
    @State private var offset: CGSize = .zero
    @GestureState private var drag: CGSize = .zero
    @GestureState private var pinch: CGFloat = 1
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var activeZoom: CGFloat { min(5, max(1, zoom * pinch)) }
    private var paths: [(id: String, path: Path)] {
        regions.map { region in
            var path = Path()
            for polygon in region.polygons {
                for ring in polygon {
                    guard let first = ring.first else { continue }
                    path.move(to: Self.project(first))
                    for point in ring.dropFirst() { path.addLine(to: Self.project(point)) }
                    path.closeSubpath()
                }
            }
            return (region.id, path)
        }
    }

    // Equirectangular projection adjusted for the mean latitude, fitted uniformly below.
    private static func project(_ coordinate: [Double]) -> CGPoint {
        CGPoint(x: (coordinate[0] + 73.8) / 14.5, y: (13.0 - coordinate[1]) / 12.8)
    }

    private func mapRect(in size: CGSize) -> CGRect {
        let aspect = 14.5 * cos(7 * Double.pi / 180) / 12.8
        let width = min(size.width - 28, (size.height - 28) * aspect)
        let height = width / aspect
        return CGRect(x: (size.width - width) / 2, y: (size.height - height) / 2, width: width, height: height)
    }

    var body: some View {
        let shapes = paths
        GeometryReader { geometry in
            let size = geometry.size
            let rect = mapRect(in: size)
            let placement = CGAffineTransform(scaleX: rect.width, y: rect.height).concatenating(CGAffineTransform(translationX: rect.minX, y: rect.minY))
            Canvas { context, _ in
                context.translateBy(x: size.width / 2 + offset.width + drag.width, y: size.height / 2 + offset.height + drag.height)
                context.scaleBy(x: activeZoom, y: activeZoom)
                context.translateBy(x: -size.width / 2, y: -size.height / 2)

                // Quiet coordinate grid provides spatial context without external basemap tiles.
                var grid = Path()
                for x in stride(from: 0.0, through: 1.0, by: 0.2) {
                    grid.move(to: CGPoint(x: rect.minX + rect.width * x, y: rect.minY))
                    grid.addLine(to: CGPoint(x: rect.minX + rect.width * x, y: rect.maxY))
                }
                for y in stride(from: 0.0, through: 1.0, by: 0.2) {
                    grid.move(to: CGPoint(x: rect.minX, y: rect.minY + rect.height * y))
                    grid.addLine(to: CGPoint(x: rect.maxX, y: rect.minY + rect.height * y))
                }
                context.stroke(grid, with: .color(DashboardStyle.ink.opacity(0.04)), lineWidth: 0.6 / activeZoom)
                for shape in shapes {
                    let path = shape.path.applying(placement)
                    let color = predictions[shape.id]?.level.color ?? .gray
                    context.fill(path, with: .color(color.opacity(shape.id == selectedID ? 0.95 : 0.60)), style: FillStyle(eoFill: true))
                    context.stroke(path, with: .color(.white.opacity(0.95)), lineWidth: 0.8 / activeZoom)
                }
                if let selected = shapes.first(where: { $0.id == selectedID }) {
                    context.stroke(selected.path.applying(placement), with: .color(DashboardStyle.ink), lineWidth: 2.2 / activeZoom)
                }
                for label in [MapLabel(name: "ZULIA", lon: -72.1, lat: 10.2), MapLabel(name: "APURE", lon: -69.0, lat: 7.0), MapLabel(name: "BOLÍVAR", lon: -63.8, lat: 6.1), MapLabel(name: "AMAZONAS", lon: -66.0, lat: 3.1)] {
                    let point = Self.project([label.lon, label.lat]).applying(placement)
                    context.draw(Text(label.name).font(.system(size: 8 / activeZoom, weight: .bold)).foregroundStyle(DashboardStyle.ink.opacity(0.75)), at: point)
                }
                let sea = Self.project([-66.0, 12.25]).applying(placement)
                context.draw(Text("CARIBBEAN SEA").font(.system(size: 8 / activeZoom, weight: .medium)).tracking(1).foregroundStyle(DashboardStyle.secondary), at: sea)
                let caracas = Self.project([-66.9036, 10.4806]).applying(placement)
                let radius = 3.5 / activeZoom
                let dot = Path(ellipseIn: CGRect(x: caracas.x - radius, y: caracas.y - radius, width: radius * 2, height: radius * 2))
                context.fill(dot, with: .color(DashboardStyle.ink))
                context.stroke(dot, with: .color(.white), lineWidth: 1.5 / activeZoom)
                context.draw(Text("Caracas").font(.system(size: 10 / activeZoom, weight: .bold)).foregroundStyle(DashboardStyle.ink), at: CGPoint(x: caracas.x, y: caracas.y - 11 / activeZoom))
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 8)
                .updating($drag) { value, state, _ in if activeZoom > 1 { state = value.translation } }
                .onEnded { value in
                    offset = bounded(CGSize(width: offset.width + value.translation.width, height: offset.height + value.translation.height), size: size)
                })
            .simultaneousGesture(MagnifyGesture()
                .updating($pinch) { value, state, _ in state = value.magnification }
                .onEnded { value in
                    zoom = min(5, max(1, zoom * value.magnification))
                    offset = bounded(offset, size: size)
                })
            .simultaneousGesture(SpatialTapGesture().onEnded { value in
                let x = (value.location.x - size.width / 2 - offset.width) / zoom + size.width / 2
                let y = (value.location.y - size.height / 2 - offset.height) / zoom + size.height / 2
                let point = CGPoint(x: (x - rect.minX) / rect.width, y: (y - rect.minY) / rect.height)
                if let hit = shapes.first(where: { $0.path.contains(point, eoFill: true) }) { selectedID = hit.id }
            })
            .accessibilityLabel("Venezuela administrative region map")
            .accessibilityHint("Use the region selector below to explore all 25 regions.")
            .accessibilityIdentifier("adm1-map-canvas")
            .overlay(alignment: .bottomTrailing) {
                HStack(spacing: 0) {
                    mapControl("Zoom out", symbol: "minus", identifier: "map-zoom-out") {
                        zoom = max(1, zoom - 1); offset = bounded(offset, size: size)
                    }.disabled(zoom <= 1)
                    Divider().frame(height: 18)
                    mapControl("Zoom in", symbol: "plus", identifier: "map-zoom-in") { zoom = min(5, zoom + 1) }.disabled(zoom >= 5)
                    Divider().frame(height: 18)
                    mapControl("Fit Venezuela", symbol: "arrow.up.left.and.arrow.down.right", identifier: "map-fit") { zoom = 1; offset = .zero }
                }
                .background(.white, in: RoundedRectangle(cornerRadius: 12))
                .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(DashboardStyle.ink.opacity(0.08)))
                .padding(10)
            }
        }
        .background(Color(red: 0.90, green: 0.94, blue: 0.95))
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: zoom)
    }

    private func bounded(_ proposed: CGSize, size: CGSize) -> CGSize {
        let x = (zoom - 1) * size.width / 2
        let y = (zoom - 1) * size.height / 2
        return CGSize(width: min(x, max(-x, proposed.width)), height: min(y, max(-y, proposed.height)))
    }
    private func mapControl(_ title: String, symbol: String, identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Image(systemName: symbol).font(.system(size: 13, weight: .semibold)).frame(width: 44, height: 44) }
            .buttonStyle(.plain).accessibilityLabel(title).accessibilityIdentifier(identifier)
    }
    private struct MapLabel { let name: String; let lon: Double; let lat: Double }
}
