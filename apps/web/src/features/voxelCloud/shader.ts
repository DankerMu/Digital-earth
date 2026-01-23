export const voxelCloudRayMarchShader = /* glsl */ `
uniform sampler2D colorTexture;
uniform sampler2D u_volumeAtlas;

uniform vec2 u_atlasGrid;      // (cols, rows)
uniform vec3 u_volumeShape;    // (width, height, depth) in voxels

uniform vec3 u_centerWorld;
uniform vec3 u_eastWorld;
uniform vec3 u_northWorld;
uniform vec3 u_upWorld;
uniform vec3 u_dimensionsMeters; // (width, height, depth) in meters

uniform float u_stepMeters;
uniform int u_maxSteps;
uniform float u_densityMultiplier;
uniform float u_extinction;

varying vec2 v_textureCoordinates;

vec3 worldToUvw(vec3 worldPos) {
  vec3 delta = worldPos - u_centerWorld;
  vec3 localMeters = vec3(
    dot(delta, u_eastWorld),
    dot(delta, u_northWorld),
    dot(delta, u_upWorld)
  );
  vec3 uvw = localMeters / u_dimensionsMeters + vec3(0.5);
  return uvw;
}

vec3 worldDirToUvwDir(vec3 worldDir) {
  vec3 localDir = vec3(
    dot(worldDir, u_eastWorld),
    dot(worldDir, u_northWorld),
    dot(worldDir, u_upWorld)
  );
  return localDir / u_dimensionsMeters;
}

bool rayAabbIntersect(vec3 origin, vec3 dir, out float tEnter, out float tExit) {
  vec3 invDir = 1.0 / dir;
  vec3 t0 = (vec3(0.0) - origin) * invDir;
  vec3 t1 = (vec3(1.0) - origin) * invDir;
  vec3 tMin = min(t0, t1);
  vec3 tMax = max(t0, t1);
  tEnter = max(max(tMin.x, tMin.y), tMin.z);
  tExit = min(min(tMax.x, tMax.y), tMax.z);
  return tExit > max(tEnter, 0.0);
}

float sampleSlice(int slice, vec2 uv) {
  float cols = u_atlasGrid.x;
  float rows = u_atlasGrid.y;
  float sliceX = float(slice % int(cols));
  float sliceY = floor(float(slice) / cols);

  vec2 atlasUv = (vec2(sliceX, sliceY) + uv) / vec2(cols, rows);
  return texture2D(u_volumeAtlas, atlasUv).r;
}

float sampleDensity(vec3 uvw) {
  float depth = u_volumeShape.z;
  float z = clamp(uvw.z, 0.0, 1.0) * max(1.0, depth - 1.0);
  float z0 = floor(z);
  float z1 = min(z0 + 1.0, depth - 1.0);
  float f = z - z0;

  vec2 uv = clamp(uvw.xy, vec2(0.0), vec2(1.0));
  float d0 = sampleSlice(int(z0), uv);
  float d1 = sampleSlice(int(z1), uv);
  return mix(d0, d1, f);
}

void main() {
  vec4 sceneColor = texture2D(colorTexture, v_textureCoordinates);

  vec2 ndc = v_textureCoordinates * 2.0 - 1.0;
  vec4 clip = vec4(ndc, 1.0, 1.0);
  vec4 eye = czm_inverseProjection * clip;
  eye /= eye.w;

  vec3 dirEye = normalize(eye.xyz);
  vec3 dirWorld = normalize((czm_inverseView * vec4(dirEye, 0.0)).xyz);
  vec3 originWorld = czm_inverseView[3].xyz;

  vec3 originUvw = worldToUvw(originWorld);
  vec3 dirUvw = worldDirToUvwDir(dirWorld);

  float tEnter;
  float tExit;
  if (!rayAabbIntersect(originUvw, dirUvw, tEnter, tExit)) {
    gl_FragColor = sceneColor;
    return;
  }

  float t = max(tEnter, 0.0);
  float tEnd = tExit;

  float transmittance = 1.0;
  vec3 cloudColor = vec3(1.0);

  for (int i = 0; i < 512; i += 1) {
    if (i >= u_maxSteps) break;
    if (t > tEnd) break;

    vec3 uvw = originUvw + dirUvw * t;
    if (any(lessThan(uvw, vec3(0.0))) || any(greaterThan(uvw, vec3(1.0)))) {
      t += u_stepMeters;
      continue;
    }

    float density = sampleDensity(uvw) * u_densityMultiplier;
    float extinctionStep = density * u_extinction * u_stepMeters;
    float absorb = exp(-extinctionStep);
    transmittance *= absorb;

    if (transmittance < 0.01) {
      transmittance = 0.0;
      break;
    }

    t += u_stepMeters;
  }

  float alpha = 1.0 - transmittance;
  vec3 outRgb = mix(sceneColor.rgb, cloudColor, alpha);
  gl_FragColor = vec4(outRgb, sceneColor.a);
}
`;
