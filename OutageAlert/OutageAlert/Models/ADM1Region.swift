import Foundation

/// ISO codes are the join key for regional predictions; source shape IDs are retained
/// for traceability. Confirm the ML model's crosswalk before connecting live data.
struct ADM1Region: Identifiable {
    let id: String
    let sourceID: String
    let name: String
    /// Polygon -> ring -> [longitude, latitude]. Inner rings are preserved as holes.
    let polygons: [[[[Double]]]]
}

enum ADM1BoundaryLoader {
    static func load(bundle: Bundle = .main) throws -> [ADM1Region] {
        guard let url = bundle.url(forResource: "venezuela-adm1", withExtension: "geojson") else {
            throw BoundaryError.missingResource
        }
        return try decode(Data(contentsOf: url))
    }

    static func decode(_ data: Data) throws -> [ADM1Region] {
        let collection = try JSONDecoder().decode(FeatureCollection.self, from: data)
        guard collection.type == "FeatureCollection", !collection.features.isEmpty else {
            throw BoundaryError.invalidGeometry
        }
        let regions = try collection.features.map { feature in
            let p = feature.properties
            guard p.shapeGroup == "VEN", p.shapeType == "ADM1", !p.shapeISO.isEmpty,
                  !feature.geometry.polygons.isEmpty else { throw BoundaryError.invalidGeometry }
            for polygon in feature.geometry.polygons {
                guard !polygon.isEmpty else { throw BoundaryError.invalidGeometry }
                for ring in polygon {
                    guard ring.count >= 4 else { throw BoundaryError.invalidGeometry }
                    for point in ring {
                        guard point.count >= 2, point[0].isFinite, point[1].isFinite,
                              (-180...180).contains(point[0]), (-90...90).contains(point[1]) else {
                            throw BoundaryError.invalidGeometry
                        }
                    }
                }
            }
            return ADM1Region(id: p.shapeISO, sourceID: p.shapeID, name: p.shapeName, polygons: feature.geometry.polygons)
        }
        guard Set(regions.map(\.id)).count == regions.count else { throw BoundaryError.duplicateRegion }
        return regions.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }

    enum BoundaryError: Error { case missingResource, invalidGeometry, duplicateRegion }
    private struct FeatureCollection: Decodable {
        let type: String
        let features: [Feature]
    }
    private struct Feature: Decodable {
        let properties: Properties
        let geometry: Geometry
    }
    private struct Properties: Decodable {
        let shapeName: String
        let shapeISO: String
        let shapeID: String
        let shapeGroup: String
        let shapeType: String
    }
    private struct Geometry: Decodable {
        let polygons: [[[[Double]]]]
        enum CodingKeys: String, CodingKey { case type, coordinates }
        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            switch try values.decode(String.self, forKey: .type) {
            case "Polygon": polygons = [try values.decode([[[Double]]].self, forKey: .coordinates)]
            case "MultiPolygon": polygons = try values.decode([[[[Double]]]].self, forKey: .coordinates)
            default: throw BoundaryError.invalidGeometry
            }
        }
    }
}
