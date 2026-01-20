from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


def _validate_percentiles(percentiles: Sequence[float]) -> tuple[float, ...]:
    normalized: list[float] = []
    for raw in percentiles:
        value = float(raw)
        if not np.isfinite(value):
            raise ValueError("percentiles must be finite numbers")
        if value <= 0.0 or value >= 100.0:
            raise ValueError("percentiles must be in (0, 100)")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


@dataclass(frozen=True)
class GridStats:
    count: np.ndarray
    mean: np.ndarray
    min: np.ndarray
    max: np.ndarray
    percentiles: dict[float, np.ndarray]


class _P2State:
    def __init__(self, *, p: float, n_cells: int) -> None:
        self.p = float(p)
        self.q = np.full((5, n_cells), np.nan, dtype=np.float32)
        self.n = np.zeros((5, n_cells), dtype=np.int32)
        self.np = np.zeros((5, n_cells), dtype=np.float32)
        self.dn = np.array(
            [0.0, self.p / 2.0, self.p, (1.0 + self.p) / 2.0, 1.0], dtype=np.float32
        )

    def initialize(self, *, sorted5: np.ndarray, mask: np.ndarray) -> None:
        self.q[:, mask] = sorted5.astype(np.float32, copy=False)
        self.n[:, mask] = np.arange(1, 6, dtype=np.int32)[:, None]
        self.np[:, mask] = np.array(
            [1.0, 1.0 + 2.0 * self.p, 1.0 + 4.0 * self.p, 3.0 + 2.0 * self.p, 5.0],
            dtype=np.float32,
        )[:, None]

    def update(self, *, x: np.ndarray, mask: np.ndarray) -> None:
        if not mask.any():
            return

        q = self.q
        n = self.n
        np_pos = self.np

        x_f = x.astype(np.float32, copy=False)

        # Find k for each cell and update extrema markers.
        k = np.zeros(x_f.shape, dtype=np.int8)
        k = k + (x_f >= q[1]).astype(np.int8)
        k = k + (x_f >= q[2]).astype(np.int8)
        k = k + (x_f >= q[3]).astype(np.int8)

        mask_lt = mask & (x_f < q[0])
        q[0, mask_lt] = x_f[mask_lt]
        mask_ge = mask & (x_f >= q[4])
        q[4, mask_ge] = x_f[mask_ge]

        # Increment marker positions for markers above k.
        for j in range(1, 5):
            inc = mask & (k < j)
            if inc.any():
                n[j, inc] += 1

        # Update desired marker positions.
        for j in range(5):
            if self.dn[j] != 0.0:
                np_pos[j, mask] += self.dn[j]

        # Adjust interior markers q2..q4 (1..3).
        for j in (1, 2, 3):
            delta = np_pos[j] - n[j].astype(np.float32)
            up = mask & (delta >= 1.0) & ((n[j + 1] - n[j]) > 1)
            down = mask & (delta <= -1.0) & ((n[j - 1] - n[j]) < -1)
            adj = up | down
            if not adj.any():
                continue

            d = np.zeros(x_f.shape, dtype=np.int8)
            d[up] = 1
            d[down] = -1

            n_jm1 = n[j - 1, adj].astype(np.float64)
            n_j = n[j, adj].astype(np.float64)
            n_jp1 = n[j + 1, adj].astype(np.float64)
            q_jm1 = q[j - 1, adj].astype(np.float64)
            q_j = q[j, adj].astype(np.float64)
            q_jp1 = q[j + 1, adj].astype(np.float64)
            d_f = d[adj].astype(np.float64)

            denom_left = n_j - n_jm1
            denom_right = n_jp1 - n_j
            denom_span = n_jp1 - n_jm1

            denom_left = np.where(denom_left == 0, 1.0, denom_left)
            denom_right = np.where(denom_right == 0, 1.0, denom_right)
            denom_span = np.where(denom_span == 0, 1.0, denom_span)

            a = (n_j - n_jm1 + d_f) * (q_jp1 - q_j) / denom_right
            b = (n_jp1 - n_j - d_f) * (q_j - q_jm1) / denom_left
            q_par = q_j + d_f * (a + b) / denom_span

            ok_par = (q_par > q_jm1) & (q_par < q_jp1)

            q_new = q_j.copy()
            q_new[ok_par] = q_par[ok_par]

            lin = ~ok_par
            if lin.any():
                d_lin = d_f[lin]
                q_j_lin = q_j[lin]
                up_lin = d_lin > 0
                down_lin = ~up_lin

                q_lin = q_j_lin.copy()
                if up_lin.any():
                    denom = n_jp1[lin][up_lin] - n_j[lin][up_lin]
                    denom = np.where(denom == 0, 1.0, denom)
                    q_lin[up_lin] = (
                        q_j_lin[up_lin] + (q_jp1[lin][up_lin] - q_j_lin[up_lin]) / denom
                    )
                if down_lin.any():
                    denom = n_jm1[lin][down_lin] - n_j[lin][down_lin]
                    denom = np.where(denom == 0, 1.0, denom)
                    q_lin[down_lin] = (
                        q_j_lin[down_lin]
                        + (q_jm1[lin][down_lin] - q_j_lin[down_lin]) / denom
                    )

                q_new[lin] = q_lin

            q[j, adj] = q_new.astype(np.float32, copy=False)
            n[j, up] += 1
            n[j, down] -= 1


class P2Quantiles:
    def __init__(self, percentiles: Sequence[float], *, n_cells: int) -> None:
        self._percentiles = _validate_percentiles(percentiles)
        self._p = [p / 100.0 for p in self._percentiles]
        self._initialized = np.zeros(n_cells, dtype=bool)
        self._init_count = np.zeros(n_cells, dtype=np.int8)
        self._init_buf = np.full((5, n_cells), np.nan, dtype=np.float32)
        self._states = [_P2State(p=p, n_cells=n_cells) for p in self._p]

    @property
    def percentiles(self) -> tuple[float, ...]:
        return self._percentiles

    def update(self, x: np.ndarray) -> None:
        x_f = x.astype(np.float32, copy=False)
        finite = np.isfinite(x_f)

        # Fill init buffer for cells that have not yet collected 5 samples.
        needs_init = (~self._initialized) & finite
        if needs_init.any():
            for row in range(5):
                mask = needs_init & (self._init_count == row)
                if not mask.any():
                    continue
                self._init_buf[row, mask] = x_f[mask]
                self._init_count[mask] += 1

            newly = (~self._initialized) & (self._init_count >= 5)
            if newly.any():
                sorted5 = np.sort(self._init_buf[:, newly].astype(np.float64), axis=0)
                for state in self._states:
                    state.initialize(sorted5=sorted5, mask=newly)
                self._initialized[newly] = True
                # The sample that completes the first 5 is already consumed by init.
                finite = finite & (~newly)

        mask = finite & self._initialized
        if not mask.any():
            return

        for state in self._states:
            state.update(x=x_f, mask=mask)

    def results(self) -> dict[float, np.ndarray]:
        out: dict[float, np.ndarray] = {}
        for percentile, state in zip(self._percentiles, self._states, strict=True):
            values = np.full(self._initialized.shape, np.nan, dtype=np.float32)
            values[self._initialized] = state.q[2, self._initialized]
            out[percentile] = values
        return out


class GridStatisticsAccumulator:
    def __init__(
        self,
        *,
        shape: tuple[int, int],
        percentiles: Sequence[float] = (),
    ) -> None:
        if len(shape) != 2:
            raise ValueError("shape must be (lat, lon)")
        self._shape = (int(shape[0]), int(shape[1]))
        self._n_cells = self._shape[0] * self._shape[1]

        self._sum = np.zeros(self._n_cells, dtype=np.float64)
        self._count = np.zeros(self._n_cells, dtype=np.int32)
        self._min = np.full(self._n_cells, np.nan, dtype=np.float32)
        self._max = np.full(self._n_cells, np.nan, dtype=np.float32)

        self._p2 = (
            P2Quantiles(percentiles, n_cells=self._n_cells) if percentiles else None
        )

    def update(self, grid: np.ndarray) -> None:
        if grid.shape != self._shape:
            raise ValueError(
                f"grid shape mismatch: expected {self._shape}, got {grid.shape}"
            )

        values = np.asarray(grid, dtype=np.float32).reshape(self._n_cells)
        finite = np.isfinite(values)

        if finite.any():
            self._sum[finite] += values[finite].astype(np.float64)
            self._count[finite] += 1

        self._min = np.fmin(self._min, values)
        self._max = np.fmax(self._max, values)

        if self._p2 is not None:
            self._p2.update(values)

    def finalize(self) -> GridStats:
        count = self._count.reshape(self._shape)
        sum_ = self._sum.reshape(self._shape)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(count > 0, (sum_ / count).astype(np.float32), np.nan)

        percentiles: dict[float, np.ndarray] = {}
        if self._p2 is not None:
            for p, values in self._p2.results().items():
                percentiles[p] = values.reshape(self._shape)

        return GridStats(
            count=count,
            mean=mean.astype(np.float32, copy=False),
            min=self._min.reshape(self._shape),
            max=self._max.reshape(self._shape),
            percentiles=percentiles,
        )


def exact_percentiles(
    *,
    samples: Iterable[np.ndarray],
    percentiles: Sequence[float],
) -> dict[float, np.ndarray]:
    pct = _validate_percentiles(percentiles)
    grids = [np.asarray(item, dtype=np.float32) for item in samples]
    if not grids:
        return {p: np.array([], dtype=np.float32) for p in pct}
    stack = np.stack(grids, axis=0).astype(np.float64, copy=False)
    out: dict[float, np.ndarray] = {}
    for p in pct:
        out[p] = np.nanpercentile(stack, p, axis=0).astype(np.float32, copy=False)
    return out
