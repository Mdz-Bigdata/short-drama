import { Component, useEffect, type ReactNode } from 'react';
import { useThree } from '@react-three/fiber';
import { Box } from 'lucide-react';

export function ContextLossGuard({ onLost }: { onLost: () => void }) {
  const canvas = useThree(state => state.gl.domElement);
  useEffect(() => {
    const lost = (event: Event) => {
      event.preventDefault();
      onLost();
    };
    canvas.addEventListener('webglcontextlost', lost);
    return () => canvas.removeEventListener('webglcontextlost', lost);
  }, [canvas, onLost]);
  return null;
}

export class ViewportBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    console.error('director desk viewport failed', error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function ViewportUnavailable({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="desk-viewport__fallback" role="status">
      <Box size={42} aria-hidden="true" />
      <strong>3D 视图暂不可用</strong>
      <span>{message}</span>
      {onRetry && <button type="button" className="desk-button" onClick={onRetry}>重试</button>}
    </div>
  );
}

export function StageLights() {
  return (
    <>
      <color attach="background" args={['#fcedef']} />
      <ambientLight intensity={1.1} />
      <hemisphereLight args={['#e76a7f', '#fdeef1', 1.4]} />
      <directionalLight position={[6, 9, 5]} intensity={2.2} />
    </>
  );
}
