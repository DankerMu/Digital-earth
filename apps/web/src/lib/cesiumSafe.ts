export function requestViewerRender(viewer: unknown): void {
  try {
    const scene = (viewer as { scene?: { requestRender?: () => void } } | null)?.scene;
    scene?.requestRender?.();
  } catch {
    // Ignore render requests during teardown / partially-destroyed Cesium instances.
  }
}

export function isCesiumDestroyed(value: unknown): boolean {
  try {
    const candidate = value as { isDestroyed?: () => boolean } | null;
    if (!candidate?.isDestroyed) return false;
    return candidate.isDestroyed();
  } catch {
    return true;
  }
}

