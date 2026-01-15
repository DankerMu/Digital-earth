# Effect Preset Schema

为 UE/Web 客户端提供统一的特效预设（Effect Preset）数据结构。

## Schema Version

`schema_version` 用于兼容未来字段扩展或语义调整。

当前支持：

- `schema_version: 1`

## 数据结构

### `EffectPreset`

| 字段 | 类型 | 约束/说明 |
|------|------|-----------|
| `effect_type` | `"rain" \| "snow" \| "fog" \| "wind" \| "storm"` | 特效类型 |
| `intensity` | `int` | 强度等级：`1-5` |
| `duration` | `float` | 持续时间（秒）；`0` 表示持续到被显式关闭 |
| `color_hint` | `string` | RGBA 提示色：`rgba(r, g, b, a)`（`r/g/b: 0-255`, `a: 0-1`） |
| `spawn_rate` | `float` | 粒子生成率（建议含义：particles/sec） |
| `particle_size` | `{min: float, max: float}` 或 `[min, max]` | 粒子大小范围（`max >= min`） |
| `wind_influence` | `float` | 风场影响系数（`>= 0`） |

### Risk Level 映射（由 `intensity` 推导）

| intensity | risk_level |
|----------|------------|
| 1-2 | `low` |
| 3 | `medium` |
| 4 | `high` |
| 5 | `extreme` |

## 配置文件

预设配置文件：`packages/shared/config/effect_presets.yaml`

顶层结构：

```yaml
schema_version: 1
presets:
  <preset_id>:
    effect_type: rain
    intensity: 2
    duration: 60
    color_hint: "rgba(180, 200, 255, 0.5)"
    spawn_rate: 80
    particle_size: [0.5, 1.5]
    wind_influence: 0.2
```

## 解析示例

### Python (Pydantic)

```py
import sys
from pathlib import Path

sys.path.insert(0, str(Path("packages/shared/src").resolve()))

from schemas.effect_preset import load_effect_presets

cfg = load_effect_presets()
print(cfg.presets["light_rain"].risk_level)
```

### TypeScript (结构参考)

```ts
export type EffectType = "rain" | "snow" | "fog" | "wind" | "storm";
export type RiskLevel = "low" | "medium" | "high" | "extreme";

export type ParticleSizeRange =
  | { min: number; max: number }
  | [number, number];

export interface EffectPreset {
  effect_type: EffectType;
  intensity: 1 | 2 | 3 | 4 | 5;
  duration: number;
  color_hint: string; // rgba(r,g,b,a)
  spawn_rate: number;
  particle_size: ParticleSizeRange;
  wind_influence: number;
}

export interface EffectPresetsFile {
  schema_version: 1;
  presets: Record<string, EffectPreset>;
}
```

