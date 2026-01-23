export class VoxelCloudPerformanceMonitor {
  private fpsHistory: number[] = [];
  private historySize = 30; // ~0.5 second at 60fps
  private downgradeThreshold = 30;
  private upgradeThreshold = 50;

  recordFrame(deltaMs: number): void {
    if (typeof deltaMs !== 'number' || !Number.isFinite(deltaMs) || deltaMs <= 0) return;
    const fps = 1000 / deltaMs;
    if (!Number.isFinite(fps) || fps <= 0) return;
    this.fpsHistory.push(fps);
    if (this.fpsHistory.length > this.historySize) {
      this.fpsHistory.splice(0, this.fpsHistory.length - this.historySize);
    }
  }

  getCurrentFps(): number {
    if (this.fpsHistory.length === 0) return 0;
    const total = this.fpsHistory.reduce((acc, value) => acc + value, 0);
    return total / this.fpsHistory.length;
  }

  shouldDowngrade(): boolean {
    if (this.fpsHistory.length < this.historySize) return false;
    return this.getCurrentFps() < this.downgradeThreshold;
  }

  shouldUpgrade(): boolean {
    if (this.fpsHistory.length < this.historySize) return false;
    return this.getCurrentFps() > this.upgradeThreshold;
  }
}

