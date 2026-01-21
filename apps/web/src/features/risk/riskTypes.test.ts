import { describe, expect, it } from 'vitest';

import {
  formatRiskLevel,
  parseRiskEvaluateResponse,
  parseRiskPoisQueryResponse,
  riskSeverityForLevel,
  splitBBoxAtDateline,
} from './riskTypes';

describe('riskTypes', () => {
  it('parses risk POIs query responses and filters invalid items', () => {
    const parsed = parseRiskPoisQueryResponse({
      page: 1,
      page_size: 100,
      total: 2,
      items: [
        {
          id: 1,
          name: ' poi-a ',
          type: ' fire ',
          lon: 120,
          lat: 30,
          alt: null,
          weight: 1,
          tags: [' hot ', '', 123],
          risk_level: 3,
        },
        { id: 'bad', name: 'bad', type: 'bad' },
      ],
    });

    expect(parsed.total).toBe(2);
    expect(parsed.items).toHaveLength(1);
    expect(parsed.items[0]).toEqual(
      expect.objectContaining({
        id: 1,
        name: 'poi-a',
        type: 'fire',
        lon: 120,
        lat: 30,
        alt: null,
        weight: 1,
        tags: ['hot'],
        risk_level: 3,
      }),
    );
  });

  it('throws for malformed risk POIs responses', () => {
    expect(() => parseRiskPoisQueryResponse(null)).toThrow(/Invalid risk POIs response/);
    expect(() => parseRiskPoisQueryResponse({ page: 1 })).toThrow(/Invalid risk POIs response/);
  });

  it('parses risk evaluate responses and filters invalid results', () => {
    const parsed = parseRiskEvaluateResponse({
      summary: {
        total: 1,
        duration_ms: 12.5,
        max_level: 4,
        avg_score: 0.75,
        level_counts: { '4': 1, bad: 'nope' },
        reasons: { wind: 1 },
      },
      results: [
        {
          poi_id: 10,
          level: 4,
          score: 0.9,
          factors: [
            {
              id: 'wind',
              value: 8.1,
              score: 0.8,
              weight: 1,
              normalized_weight: 1,
              contribution: 0.5,
            },
          ],
          reasons: [
            {
              factor_id: 'wind',
              factor_name: 'Wind',
              value: 8.1,
              threshold: 5,
              contribution: 0.5,
            },
          ],
        },
        { poi_id: 'bad' },
      ],
    });

    expect(parsed.summary.total).toBe(1);
    expect(parsed.summary.level_counts).toEqual({ '4': 1 });
    expect(parsed.results).toHaveLength(1);
    expect(parsed.results[0]).toEqual(
      expect.objectContaining({
        poi_id: 10,
        level: 4,
      }),
    );
    expect(parsed.results[0]?.reasons[0]).toEqual(
      expect.objectContaining({ factor_name: 'Wind', threshold: 5 }),
    );
  });

  it('maps risk levels to severities and formats labels', () => {
    expect(riskSeverityForLevel(null)).toBe('unknown');
    expect(riskSeverityForLevel(1)).toBe('low');
    expect(riskSeverityForLevel(3)).toBe('medium');
    expect(riskSeverityForLevel(5)).toBe('high');

    expect(formatRiskLevel(null)).toBe('--');
    expect(formatRiskLevel(3.2)).toBe('3');
  });

  it('splits dateline-crossing bboxes', () => {
    expect(
      splitBBoxAtDateline({ min_x: 170, min_y: 10, max_x: -170, max_y: 20 }),
    ).toEqual([
      { min_x: 170, min_y: 10, max_x: 180, max_y: 20 },
      { min_x: -180, min_y: 10, max_x: -170, max_y: 20 },
    ]);
  });
});

