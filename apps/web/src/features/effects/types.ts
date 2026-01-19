export type RiskLevel = 'low' | 'medium' | 'high' | 'extreme';

export type EffectType = 'rain' | 'snow' | 'fog' | 'wind' | 'storm' | 'debris_flow';

export type ParticleSizeRange = {
  min: number;
  max: number;
};

export type EffectPresetItem = {
  id: string;
  effect_type: EffectType;
  intensity: number;
  duration: number;
  color_hint: string;
  spawn_rate: number;
  particle_size: ParticleSizeRange;
  wind_influence: number;
  risk_level: RiskLevel;
};

