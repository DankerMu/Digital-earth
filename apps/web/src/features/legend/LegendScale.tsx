import type { LegendConfig } from './types';

function computePercents(thresholds: number[]): number[] {
  if (thresholds.length === 0) return [];

  const min = thresholds[0];
  const max = thresholds[thresholds.length - 1];
  if (max === min) return thresholds.map(() => 0);

  return thresholds.map((value) => ((value - min) / (max - min)) * 100);
}

function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

export function LegendScale(props: { legend: LegendConfig }) {
  const percents = computePercents(props.legend.thresholds);
  const gradient = `linear-gradient(to right, ${props.legend.colors
    .map((color, index) => `${color} ${formatPercent(percents[index] ?? 0)}`)
    .join(', ')})`;

  return (
    <div>
      <div
        data-testid="legend-gradient"
        style={{
          height: 12,
          borderRadius: 999,
          border: '1px solid rgba(148, 163, 184, 0.35)',
          background: gradient,
        }}
      />

      <div
        style={{
          position: 'relative',
          height: 18,
          marginTop: 8,
          fontSize: 12,
          color: 'rgba(226, 232, 240, 0.9)',
        }}
      >
        {props.legend.labels.map((label, index) => {
          const percent = percents[index] ?? 0;
          const isFirst = index === 0;
          const isLast = index === props.legend.labels.length - 1;

          const transform = isFirst
            ? 'translateX(0)'
            : isLast
              ? 'translateX(-100%)'
              : 'translateX(-50%)';

          return (
            <span
              key={`${label}-${index}`}
              data-testid={`legend-tick-${index}`}
              style={{
                position: 'absolute',
                left: formatPercent(percent),
                transform,
                whiteSpace: 'nowrap',
              }}
            >
              {label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

