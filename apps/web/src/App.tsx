import { Suspense, lazy, useMemo } from 'react';
import ErrorBoundary from './components/ErrorBoundary';
import { AppLayout } from './features/layout/AppLayout';

const VoxelCloudPocPage = lazy(() =>
  import('./features/voxelCloud/VoxelCloudPocPage').then((mod) => ({
    default: mod.VoxelCloudPocPage,
  })),
);

function isVoxelCloudPocRoute(): boolean {
  try {
    const search = globalThis.location?.search;
    if (!search) return false;
    const params = new URLSearchParams(search);
    const poc = params.get('poc')?.trim().toLowerCase();
    if (poc === 'voxel-cloud' || poc === 'voxelcloud') return true;
    const flag = params.get('voxelCloudPoc') ?? params.get('voxelcloudpoc');
    return flag === '1' || flag === 'true';
  } catch {
    return false;
  }
}

export default function App() {
  const showVoxelCloudPoc = useMemo(() => isVoxelCloudPocRoute(), []);
  return (
    <ErrorBoundary>
      {showVoxelCloudPoc ? (
        <Suspense fallback={<div className="h-screen w-screen bg-slate-950 text-slate-100" />}>
          <VoxelCloudPocPage />
        </Suspense>
      ) : (
        <AppLayout />
      )}
    </ErrorBoundary>
  );
}
