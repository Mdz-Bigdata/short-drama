import { Component, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Grid, Line, OrbitControls, PerspectiveCamera, Text } from '@react-three/drei';
import { Canvas, useThree } from '@react-three/fiber';
import { Box } from 'lucide-react';

import { parseAspect } from '../floorPlanGeometry';
import { actorsInShot, type StageActor, type StageCamera, type StageLandmark, type StagePlan, type StageShot } from '../spatialTypes';
import { t } from '../../../i18n';

export type StageViewMode = 'director' | 'camera';

interface Props {
  plan: StagePlan;
  shot?: StageShot;
  mode: StageViewMode;
}

// How much of a standing body each posture keeps (mirrors the backend's POSTURE_HEIGHT).
const POSTURE_HEIGHT: Record<string, number> = {
  stand: 1, walk: 1, run: 0.96, fight: 0.94, lean: 0.97, bow: 0.8, sit: 0.74, crouch: 0.6, kneel: 0.68, lie: 0.22,
};
const ROLE_COLOR: Record<StageActor['role'], string> = { principal: '#e3546c', supporting: '#e67563', crowd: '#8b6d79' };
const LANDMARK_COLOR: Record<StageLandmark['kind'], string> = {
  prop: '#ce8818', furniture: '#6d555f', architecture: '#927481', light: '#e68100',
};

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(window.WebGLRenderingContext && (canvas.getContext('webgl2') || canvas.getContext('webgl')));
  } catch {
    return false;
  }
}

/**
 * A blockout figure: proportions only, no limbs. The storyboard's white-model rules ask for
 * stand-ins without arms and legs, because a model copies a stand-in's pose as the character's.
 */
function ActorFigure({ actor, subject, labelled }: { actor: StageActor; subject: boolean; labelled: boolean }) {
  const height = actor.height_m * (POSTURE_HEIGHT[actor.posture] ?? 1);
  const head = 0.11;
  const body = Math.max(0.2, height - head * 2);
  const color = ROLE_COLOR[actor.role];
  const lying = actor.posture === 'lie';
  return (
    <group position={[actor.position[0], 0, actor.position[1]]} rotation={[0, (actor.yaw_deg * Math.PI) / 180, 0]}>
      <group rotation={lying ? [-Math.PI / 2, 0, 0] : [0, 0, 0]} position={lying ? [0, 0.2, 0] : [0, 0, 0]}>
        <mesh position={[0, body / 2, 0]}>
          <capsuleGeometry args={[0.2, Math.max(0.05, body - 0.4), 6, 14]} />
          <meshStandardMaterial color={color} roughness={0.55} emissive={subject ? color : '#fcebee'} emissiveIntensity={subject ? 0.25 : 0} />
        </mesh>
        <mesh position={[0, body + head, 0]}>
          <sphereGeometry args={[head, 18, 14]} />
          <meshStandardMaterial color={color} roughness={0.5} />
        </mesh>
        {/* The nose: which way the character faces is the whole point of the figure. */}
        <mesh position={[0, body + head, head + 0.05]} rotation={[Math.PI / 2, 0, 0]}>
          <coneGeometry args={[0.04, 0.12, 10]} />
          <meshStandardMaterial color="#221b1e" />
        </mesh>
      </group>
      {labelled && (
        <Text position={[0, height + 0.28, 0]} fontSize={0.16} color="#e87084" anchorX="center" anchorY="bottom" outlineWidth={0.012} outlineColor="#fcedef">
          {actor.name}
        </Text>
      )}
    </group>
  );
}

function LandmarkBlock({ landmark, labelled }: { landmark: StageLandmark; labelled: boolean }) {
  const [width, depth, height] = landmark.size;
  return (
    <group position={[landmark.position[0], 0, landmark.position[1]]}>
      <mesh position={[0, height / 2, 0]}>
        <boxGeometry args={[width, height, depth]} />
        <meshStandardMaterial color={LANDMARK_COLOR[landmark.kind]} roughness={0.8} transparent opacity={0.82} />
      </mesh>
      {labelled && (
        <Text position={[0, height + 0.18, 0]} fontSize={0.13} color="#46373e" anchorX="center" anchorY="bottom">{landmark.name}</Text>
      )}
    </group>
  );
}

function CameraRig({ camera, selected, label }: { camera: StageCamera; selected: boolean; label: string }) {
  const lines = useMemo(() => {
    const position = camera.position;
    const target = camera.target;
    const forward = [target[0] - position[0], target[1] - position[1], target[2] - position[2]];
    const length = Math.hypot(...forward) || 1;
    const f = forward.map(value => value / length);
    const upGuess = Math.abs(f[1]) > 0.999 ? [0, 0, -1] : [0, 1, 0];
    const right = [f[1] * upGuess[2] - f[2] * upGuess[1], f[2] * upGuess[0] - f[0] * upGuess[2], f[0] * upGuess[1] - f[1] * upGuess[0]];
    const rightLength = Math.hypot(...right) || 1;
    const r = right.map(value => value / rightLength);
    const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
    const reach = selected ? Math.min(length, 6) : 0.7;
    const halfHeight = Math.tan((camera.fov_deg * Math.PI) / 360) * reach;
    const halfWidth = halfHeight * parseAspect(camera.aspect);
    const corner = (sx: number, sy: number): [number, number, number] => [
      position[0] + f[0] * reach + r[0] * halfWidth * sx + u[0] * halfHeight * sy,
      position[1] + f[1] * reach + r[1] * halfWidth * sx + u[1] * halfHeight * sy,
      position[2] + f[2] * reach + r[2] * halfWidth * sx + u[2] * halfHeight * sy,
    ];
    const corners = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)];
    const apex: [number, number, number] = [position[0], position[1], position[2]];
    return [...corners.map(point => [apex, point]), [...corners, corners[0]]] as [number, number, number][][];
  }, [camera, selected]);
  const color = selected ? '#e6a000' : '#957884';
  return (
    <group>
      {lines.map((points, index) => <Line key={index} points={points} color={color} lineWidth={selected ? 1.6 : 0.8} />)}
      <mesh position={[camera.position[0], camera.position[1], camera.position[2]]}>
        <boxGeometry args={[0.16, 0.12, 0.2]} />
        <meshStandardMaterial color={color} />
      </mesh>
      <Text position={[camera.position[0], camera.position[1] + 0.2, camera.position[2]]} fontSize={0.13} color={color} anchorX="center">{label}</Text>
    </group>
  );
}

function LookAt({ target }: { target: [number, number, number] }) {
  const camera = useThree(state => state.camera);
  const invalidate = useThree(state => state.invalidate);
  useEffect(() => {
    camera.lookAt(target[0], target[1], target[2]);
    camera.updateProjectionMatrix();
    invalidate();
  }, [camera, invalidate, target]);
  return null;
}

class ViewportBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    console.error('spatial stage viewport failed', error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function Unavailable({ message }: { message: string }) {
  return (
    <div className="spatial-viewport__fallback" role="status">
      <Box size={42} aria-hidden="true" />
      <strong>{t('3D 预览暂不可用')}</strong>
      <span>{message}</span>
    </div>
  );
}

export default function SpatialStageViewport({ plan, shot, mode }: Props) {
  const [canRender] = useState(webglAvailable);
  const actors = useMemo(() => actorsInShot(plan, shot), [plan, shot]);
  const camera = plan.cameras.find(item => item.id === shot?.camera_id);
  const lens = mode === 'camera' && camera ? camera : undefined;
  const aspect = parseAspect(plan.aspect_ratio);
  const centre = useMemo<[number, number, number]>(() => {
    const solid = plan.actors.filter(actor => actor.role !== 'crowd');
    const pool = solid.length ? solid : plan.actors;
    if (!pool.length) return [0, 1, 0];
    return [pool.reduce((sum, a) => sum + a.position[0], 0) / pool.length, 1, pool.reduce((sum, a) => sum + a.position[1], 0) / pool.length];
  }, [plan.actors]);
  const axisPoints = useMemo<[number, number, number][]>(() => {
    const [sx, sz] = plan.axis.start;
    const [ex, ez] = plan.axis.end;
    const dx = ex - sx;
    const dz = ez - sz;
    const length = Math.hypot(dx, dz) || 1;
    return [[sx - (dx / length) * 3, 0.02, sz - (dz / length) * 3], [ex + (dx / length) * 3, 0.02, ez + (dz / length) * 3]];
  }, [plan.axis]);

  if (!canRender) return <Unavailable message="当前浏览器或设备不支持 WebGL，请使用俯视图。" />;
  const fallback = <Unavailable message="3D 场景渲染失败，俯视图仍可编辑。" />;
  const lensTarget = lens ? [lens.target[0], lens.target[1], lens.target[2]] as [number, number, number] : centre;

  return (
    <div className={`spatial-viewport is-${mode}`} role="region" aria-label={mode === 'camera' ? t('机位视角预览') : t('导演视角预览')}>
      <ViewportBoundary fallback={fallback}>
        {/* In camera view the canvas itself takes the delivery aspect, so what is inside it is the frame. */}
        <div className="spatial-viewport__frame" style={lens ? { aspectRatio: String(aspect) } : undefined}>
          <Canvas dpr={[1, 1.5]} frameloop="demand" gl={{ antialias: true, powerPreference: 'high-performance', preserveDrawingBuffer: true }}>
            <color attach="background" args={['#fcedef']} />
            <ambientLight intensity={1.1} />
            <hemisphereLight args={['#e76a7f', '#fdeef1', 1.4]} />
            <directionalLight position={[6, 9, 5]} intensity={2.2} />
            {lens ? (
              <>
                <PerspectiveCamera makeDefault fov={lens.fov_deg} near={0.05} far={500} position={[lens.position[0], lens.position[1], lens.position[2]]} />
                <LookAt target={lensTarget} />
              </>
            ) : (
              <>
                <PerspectiveCamera makeDefault fov={42} near={0.05} far={500} position={[centre[0] + 5.5, 5, centre[2] + 8]} />
                <OrbitControls makeDefault enableDamping target={centre} minDistance={1} maxDistance={80} maxPolarAngle={Math.PI / 2.02} />
              </>
            )}
            {!lens && (
              <Grid
                args={[40, 40]} cellSize={1} cellThickness={0.5} cellColor="#fef9fa"
                sectionSize={5} sectionThickness={0.9} sectionColor="#e14962" fadeDistance={45} fadeStrength={1.4} infiniteGrid
              />
            )}
            <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.005, 0]}>
              <planeGeometry args={[200, 200]} />
              <meshStandardMaterial color="#fdeff1" roughness={1} />
            </mesh>
            {!lens && plan.axis.kind !== 'none' && <Line points={axisPoints} color="#e60000" lineWidth={1.4} dashed dashSize={0.25} gapSize={0.15} />}
            {plan.landmarks.map(landmark => <LandmarkBlock key={landmark.id} landmark={landmark} labelled={!lens} />)}
            {actors.map(actor => (
              <ActorFigure key={actor.id} actor={actor} subject={Boolean(shot?.subjects.includes(actor.name))} labelled={!lens} />
            ))}
            {!lens && plan.cameras.map(item => {
              const owner = plan.shots.find(candidate => candidate.camera_id === item.id);
              return <CameraRig key={item.id} camera={item} selected={item.id === camera?.id} label={owner ? String(owner.shot_id) : item.id} />;
            })}
          </Canvas>
        </div>
      </ViewportBoundary>
      <div className="spatial-viewport__hint">
        {lens
          ? `第 ${shot?.shot_id} 镜 · ${lens.shot_size} · ${lens.lens_mm}mm · ${plan.aspect_ratio}（白模不带四肢，仅示意站位与景别）`
          : '拖动旋转 · 滚轮缩放 · 右键平移 · 红色虚线为轴线'}
      </div>
    </div>
  );
}
