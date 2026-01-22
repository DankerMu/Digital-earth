export type LonLat = { lon: number; lat: number };

export type BBox = {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
};

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

export function bboxFromLonLat(vertices: LonLat[]): BBox | null {
  if (vertices.length === 0) return null;

  let minLon = vertices[0]!.lon;
  let maxLon = vertices[0]!.lon;
  let minLat = vertices[0]!.lat;
  let maxLat = vertices[0]!.lat;

  for (const vertex of vertices.slice(1)) {
    minLon = Math.min(minLon, vertex.lon);
    maxLon = Math.max(maxLon, vertex.lon);
    minLat = Math.min(minLat, vertex.lat);
    maxLat = Math.max(maxLat, vertex.lat);
  }

  return { min_x: minLon, min_y: minLat, max_x: maxLon, max_y: maxLat };
}

export function geoJsonRingFromLonLat(vertices: LonLat[]): number[][] {
  if (vertices.length === 0) return [];

  const ring = vertices.map((vertex) => [vertex.lon, vertex.lat]);
  const first = vertices[0]!;
  const last = vertices[vertices.length - 1]!;
  if (!Object.is(first.lon, last.lon) || !Object.is(first.lat, last.lat)) {
    ring.push([first.lon, first.lat]);
  }
  return ring;
}

export function geoJsonPolygonFromLonLat(
  vertices: LonLat[],
): { type: 'Polygon'; coordinates: number[][][] } | null {
  if (vertices.length < 3) return null;
  return { type: 'Polygon', coordinates: [geoJsonRingFromLonLat(vertices)] };
}

/**
 * Returns the approximate spherical polygon area in square kilometers.
 * Uses the same algorithm as mapbox/geojson-area (spherical excess approximation).
 */
export function polygonAreaKm2(vertices: LonLat[]): number | null {
  if (vertices.length < 3) return null;

  // WGS84 semi-major axis; aligns well with Cesium's default ellipsoid.
  const earthRadiusMeters = 6_378_137;

  let sum = 0;
  for (let index = 0; index < vertices.length; index += 1) {
    const current = vertices[index]!;
    const next = vertices[(index + 1) % vertices.length]!;

    const lon1 = toRadians(current.lon);
    const lon2 = toRadians(next.lon);
    const lat1 = toRadians(current.lat);
    const lat2 = toRadians(next.lat);

    sum += (lon2 - lon1) * (2 + Math.sin(lat1) + Math.sin(lat2));
  }

  const areaMeters2 = (sum * earthRadiusMeters * earthRadiusMeters) / 2;
  return Math.abs(areaMeters2) / 1_000_000;
}

type Point2 = { x: number; y: number };

function orientation(a: Point2, b: Point2, c: Point2): number {
  return (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y);
}

function onSegment(a: Point2, b: Point2, c: Point2): boolean {
  return (
    Math.min(a.x, c.x) <= b.x &&
    b.x <= Math.max(a.x, c.x) &&
    Math.min(a.y, c.y) <= b.y &&
    b.y <= Math.max(a.y, c.y)
  );
}

function segmentsIntersect(p1: Point2, q1: Point2, p2: Point2, q2: Point2): boolean {
  const o1 = orientation(p1, q1, p2);
  const o2 = orientation(p1, q1, q2);
  const o3 = orientation(p2, q2, p1);
  const o4 = orientation(p2, q2, q1);

  if (o1 === 0 && onSegment(p1, p2, q1)) return true;
  if (o2 === 0 && onSegment(p1, q2, q1)) return true;
  if (o3 === 0 && onSegment(p2, p1, q2)) return true;
  if (o4 === 0 && onSegment(p2, q1, q2)) return true;

  return (o1 > 0) !== (o2 > 0) && (o3 > 0) !== (o4 > 0);
}

function isAdjacentEdge(a: number, b: number, vertexCount: number): boolean {
  if (a === b) return true;
  if ((a + 1) % vertexCount === b) return true;
  if ((b + 1) % vertexCount === a) return true;
  return false;
}

export function polygonHasSelfIntersections(vertices: LonLat[]): boolean {
  if (vertices.length < 4) return false;

  const points = vertices.map((vertex) => ({ x: vertex.lon, y: vertex.lat }));

  for (let edgeA = 0; edgeA < points.length; edgeA += 1) {
    const a1 = points[edgeA]!;
    const a2 = points[(edgeA + 1) % points.length]!;

    for (let edgeB = edgeA + 1; edgeB < points.length; edgeB += 1) {
      if (isAdjacentEdge(edgeA, edgeB, points.length)) continue;

      const b1 = points[edgeB]!;
      const b2 = points[(edgeB + 1) % points.length]!;

      if (segmentsIntersect(a1, a2, b1, b2)) return true;
    }
  }

  return false;
}

