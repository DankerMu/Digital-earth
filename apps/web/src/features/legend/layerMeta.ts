import type { LayerType } from './types';

export const LAYER_META: Record<LayerType, { title: string; unit: string }> = {
  temperature: { title: '温度', unit: '°C' },
  cloud: { title: '云量', unit: '%' },
  precipitation: { title: '降水', unit: 'mm' },
  wind: { title: '风速', unit: 'm/s' },
};

