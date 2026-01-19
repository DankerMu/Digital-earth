import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type PerformanceModeState = {
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
};

export const usePerformanceModeStore = create<PerformanceModeState>()(
  persist(
    (set) => ({
      enabled: false,
      setEnabled: (enabled) => set({ enabled }),
    }),
    { name: 'digital-earth.performanceMode' }
  )
);

