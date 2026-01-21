import ErrorBoundary from './components/ErrorBoundary';
import { AppLayout } from './features/layout/AppLayout';

export default function App() {
  return (
    <ErrorBoundary>
      <AppLayout />
    </ErrorBoundary>
  );
}
