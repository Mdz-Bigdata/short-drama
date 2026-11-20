import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Copy, Download, X } from 'lucide-react';

import { ApiError } from '../../../api/client';
import { fetchBlockingDiagrams } from '../blockingDiagramApi';
import {
  DIAGRAM_HEIGHT, DIAGRAM_WIDTH, arrowHead, cameraCone, contactStar, darker, diagramFileName, footprint, forwardOf, gridLines, legendText,
  metresLabel, pathOf, placeTags, postureHeight, projectionFor, ringPoints, ringRadii, routeMidpoint,
  type BlockingDiagram, type BlockingDiagramSeries, type DiagramCamera, type DiagramDistance, type DiagramEffect, type DiagramFigure,
  type DiagramPiece, type DiagramStrike, type Point, type Projection,
} from '../lib/blockingDiagram';
import { useEscapeToClose } from './useEscapeToClose';

import '../DeskDiagram.css';

// 图是给人看、也可以交给出图模型当参考的「白模」：永远是浅色底，不跟界面主题走。
const PAPER = '#F5F5F0';
const GRID = '#DCDCD6';
const GRID_MAJOR = '#BDBDB6';
const PIECE_FILL = '#E6E6E1';
const PIECE_TOP = '#F0F0EB';
const PIECE_LINE = '#BEBEB8';
const INK = '#2B2B2B';
const CONE_PLAIN = '#7A7A7A';
const FONT = '"PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "Hiragino Sans GB", system-ui, sans-serif';

const polygon = (points: Point[]) => points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');

function Piece({ piece, projection }: { piece: DiagramPiece; projection: Projection }) {
  const base = footprint(piece).map(([x, z]) => projection.at(x, z, piece.elevation_m));
  const top = footprint(piece).map(([x, z]) => projection.at(x, z, piece.elevation_m + piece.size[2]));
  const flat = projection.rise * piece.size[2] < 1.5;
  return (
    <g>
      <polygon points={polygon(base)} fill={PIECE_FILL} stroke={PIECE_LINE} strokeWidth={1.5} opacity={0.9} />
      {!flat && base.map((point, index) => (
        <line key={index} x1={point[0]} y1={point[1]} x2={top[index][0]} y2={top[index][1]} stroke={PIECE_LINE} strokeWidth={1.5} />
      ))}
      {!flat && <polygon points={polygon(top)} fill={PIECE_TOP} stroke={PIECE_LINE} strokeWidth={1.5} opacity={0.92} />}
    </g>
  );
}

function Figure({ figure, projection }: { figure: DiagramFigure; projection: Projection }) {
  const [x, z] = figure.position;
  const scale = projection.scale;
  const forward = forwardOf(figure.yaw_deg);
  const right: Point = [-forward[1], forward[0]];
  const feet = projection.at(x, z);
  const outline = darker(figure.color);
  const opacity = figure.extra ? 0.75 : 1;
  const nose = [
    projection.at(x + forward[0] * 0.62, z + forward[1] * 0.62),
    projection.at(x + forward[0] * 0.22 + right[0] * 0.17, z + forward[1] * 0.22 + right[1] * 0.17),
    projection.at(x + forward[0] * 0.22 - right[0] * 0.17, z + forward[1] * 0.22 - right[1] * 0.17),
  ];
  const shadow = <ellipse cx={feet[0]} cy={feet[1]} rx={0.34 * scale} ry={Math.max(3, 0.34 * projection.run)} fill={outline} opacity={0.2} />;

  if (figure.posture === 'lie') {
    const half = figure.height_m / 2;
    const head = projection.at(x + forward[0] * half, z + forward[1] * half, 0.14);
    const toe = projection.at(x - forward[0] * half, z - forward[1] * half, 0.14);
    return (
      <g opacity={opacity}>
        {shadow}
        <line x1={toe[0]} y1={toe[1]} x2={head[0]} y2={head[1]} stroke={figure.color} strokeWidth={Math.max(8, 0.34 * scale)} strokeLinecap="round" />
        <circle cx={head[0]} cy={head[1]} r={Math.max(5, 0.13 * scale)} fill={figure.color} stroke={outline} strokeWidth={1.5} />
      </g>
    );
  }

  const height = figure.height_m * postureHeight(figure.posture);
  const headRadius = Math.max(5, 0.125 * scale);
  const bodyTop = projection.at(x, z, Math.max(0.2, height - 0.25));
  const headCentre = projection.at(x, z, Math.max(0.3, height - 0.125));
  const bodyWidth = Math.max(10, 0.44 * scale);
  const bodyHeight = feet[1] - bodyTop[1];
  // Seen from straight above there is no height to draw: shoulders and a head, with the nose showing the facing.
  const fromAbove = bodyHeight < bodyWidth * 0.6;
  return (
    <g opacity={opacity}>
      {shadow}
      <polygon points={polygon(nose)} fill={figure.color} stroke={outline} strokeWidth={1} opacity={0.85} />
      {fromAbove ? (
        <>
          <ellipse cx={feet[0]} cy={feet[1]} rx={bodyWidth * 0.62} ry={Math.max(6, bodyWidth * 0.62 * Math.sin(projection.tilt))} fill={figure.color} stroke={outline} strokeWidth={1.5} />
          <circle cx={headCentre[0]} cy={headCentre[1]} r={headRadius} fill={figure.color} stroke={outline} strokeWidth={1.5} />
        </>
      ) : (
        <>
          <rect x={feet[0] - bodyWidth / 2} y={bodyTop[1]} width={bodyWidth} height={bodyHeight} rx={bodyWidth / 2} fill={figure.color} stroke={outline} strokeWidth={1.5} />
          <circle cx={headCentre[0]} cy={headCentre[1] - headRadius * 0.6} r={headRadius} fill={figure.color} stroke={outline} strokeWidth={1.5} />
        </>
      )}
    </g>
  );
}

/** The top of a figure's head on the picture: where its name tag hangs from. */
function headOf(figure: DiagramFigure, projection: Projection): Point {
  if (figure.posture === 'lie') return projection.at(figure.position[0], figure.position[1], 0.3);
  const height = figure.height_m * postureHeight(figure.posture);
  const point = projection.at(figure.position[0], figure.position[1], height);
  return [point[0], point[1] - Math.max(5, 0.125 * projection.scale) * 0.6];
}

function Lens({ camera, projection }: { camera: DiagramCamera; projection: Projection }) {
  const cone = cameraCone(camera);
  const wedge = cone.points.map(([x, z]) => projection.at(x, z));
  const colour = camera.color || CONE_PLAIN;
  const dx = camera.target[0] - camera.position[0];
  const dz = camera.target[1] - camera.position[1];
  const length = Math.hypot(dx, dz) || 1;
  const forward: Point = [dx / length, dz / length];
  const right: Point = [-forward[1], forward[0]];
  const corner = (along: number, across: number): Point => projection.at(
    camera.position[0] + forward[0] * along + right[0] * across, camera.position[1] + forward[1] * along + right[1] * across,
  );
  const body = [corner(-0.42, -0.2), corner(0.05, -0.2), corner(0.05, 0.2), corner(-0.42, 0.2)];
  const hood = [corner(0.05, -0.1), corner(0.3, -0.19), corner(0.3, 0.19), corner(0.05, 0.1)];
  const at = projection.at(camera.position[0], camera.position[1]);
  const label = camera.far_m ? `${camera.label} · ${camera.far_m}m` : camera.label;
  const labelWidth = label.length * 12.5 + 18;
  const end = camera.end_position ? projection.at(camera.end_position[0], camera.end_position[1]) : null;
  return (
    <g opacity={camera.candidate ? 0.6 : 1}>
      <polygon points={polygon(wedge)} fill={colour} fillOpacity={0.15} stroke={colour} strokeOpacity={0.55} strokeWidth={1.5} strokeDasharray={camera.candidate ? '6 5' : undefined} />
      {end && (
        <>
          <line x1={at[0]} y1={at[1]} x2={end[0]} y2={end[1]} stroke={INK} strokeWidth={2.5} />
          <polygon points={polygon(arrowHead(at, end, 14))} fill={INK} />
        </>
      )}
      <polygon points={polygon(body)} fill={INK} />
      <polygon points={polygon(hood)} fill={INK} />
      <rect x={at[0] - labelWidth / 2} y={at[1] + 16} width={labelWidth} height={26} rx={6} fill={INK} />
      <text x={at[0]} y={at[1] + 34.5} textAnchor="middle" fontSize={17} fontWeight={700} fill="#FFFFFF" fontFamily={FONT}>{label}</text>
    </g>
  );
}

/** A short label on a white pill, centred on `at`. */
function Pill({ at, text, color, size = 17 }: { at: Point; text: string; color: string; size?: number }) {
  let ems = 0;
  for (const char of text) ems += char.charCodeAt(0) < 0x100 ? 0.58 : 1;
  const width = Math.ceil(ems * size + 14);
  const height = size + 9;
  return (
    <g>
      <rect x={at[0] - width / 2} y={at[1] - height / 2} width={width} height={height} rx={height / 2} fill="#FFFFFF" fillOpacity={0.95} stroke={color} strokeWidth={2} />
      <text x={at[0]} y={at[1] + size * 0.36} textAnchor="middle" fontSize={size} fontWeight={700} fill={darker(color, 0.3)} fontFamily={FONT}>{text}</text>
    </g>
  );
}

const between = (a: Point, b: Point, part = 0.5): Point => [a[0] + (b[0] - a[0]) * part, a[1] + (b[1] - a[1]) * part];

/** A ruler between two figures: a thin line on the floor with a tick at each end and the metres on it. */
function Ruler({ distance, projection }: { distance: DiagramDistance; projection: Projection }) {
  const from = projection.at(distance.from[0], distance.from[1]);
  const to = projection.at(distance.to[0], distance.to[1]);
  const length = Math.hypot(to[0] - from[0], to[1] - from[1]) || 1;
  const across: Point = [(-(to[1] - from[1]) / length) * 9, ((to[0] - from[0]) / length) * 9];
  return (
    <g>
      <line x1={from[0]} y1={from[1]} x2={to[0]} y2={to[1]} stroke={INK} strokeWidth={1.5} opacity={0.75} />
      {[from, to].map((point, index) => (
        <line key={index} x1={point[0] - across[0]} y1={point[1] - across[1]} x2={point[0] + across[0]} y2={point[1] + across[1]} stroke={INK} strokeWidth={1.5} opacity={0.75} />
      ))}
    </g>
  );
}

/** The floor part of a strike: a dotted line from the hand to the contact point, and the way the struck figure is driven. */
function StrikeLine({ strike, projection }: { strike: DiagramStrike; projection: Projection }) {
  const from = projection.at(strike.from[0], strike.from[1]);
  const to = projection.at(strike.to[0], strike.to[1]);
  const force = strike.force_to ? projection.at(strike.force_to[0], strike.force_to[1]) : null;
  const ink = darker(strike.color, 0.2);
  return (
    <g>
      <line x1={from[0]} y1={from[1]} x2={to[0]} y2={to[1]} stroke={strike.color} strokeWidth={7} strokeDasharray="2 12" strokeLinecap="round" />
      <polygon points={polygon(arrowHead(from, to, 20))} fill={strike.color} />
      {force && (
        <>
          <line x1={to[0]} y1={to[1]} x2={force[0]} y2={force[1]} stroke={ink} strokeWidth={4} />
          <polygon points={polygon(arrowHead(to, force, 16))} fill={ink} />
        </>
      )}
    </g>
  );
}

/** An effect's placeholder range: thin rings on the floor, and a thin arrow from whoever sends it. */
function EffectRings({ effect, projection }: { effect: DiagramEffect; projection: Projection }) {
  const centre = projection.at(effect.center[0], effect.center[1]);
  const from = effect.from ? projection.at(effect.from[0], effect.from[1]) : null;
  return (
    <g>
      {ringRadii(effect.radius_m, effect.rings).map((radius, index) => (
        <polygon
          key={radius} points={polygon(ringPoints(effect.center, radius, projection))} fill={effect.color} fillOpacity={index === 0 ? 0.05 : 0}
          stroke={effect.color} strokeWidth={2} strokeDasharray={index === 0 ? undefined : '8 6'}
        />
      ))}
      {from && (
        <>
          <line x1={from[0]} y1={from[1]} x2={centre[0]} y2={centre[1]} stroke={effect.color} strokeWidth={2} />
          <polygon points={polygon(arrowHead(from, centre, 13))} fill={effect.color} />
        </>
      )}
      <circle cx={centre[0]} cy={centre[1]} r={4} fill={effect.color} />
    </g>
  );
}

export function DiagramPicture({ diagram, series, tiltDeg, svgRef }: {
  diagram: BlockingDiagram; series: BlockingDiagramSeries; tiltDeg: number; svgRef?: React.Ref<SVGSVGElement>;
}) {
  const projection = useMemo(() => projectionFor(diagram.bounds, tiltDeg), [diagram.bounds, tiltDeg]);
  const lines = useMemo(() => gridLines(diagram.bounds, projection, series.grid.major_every), [diagram.bounds, projection, series.grid.major_every]);
  const [lowX, lowZ, highX, highZ] = diagram.bounds;
  const floor = [projection.at(lowX, lowZ), projection.at(highX, lowZ), projection.at(highX, highZ), projection.at(lowX, highZ)];
  // Far things first, so what stands nearer the viewer covers what is behind it.
  const solids = [
    ...diagram.pieces.map(piece => ({ depth: piece.position[1], node: <Piece key={`p-${piece.name}-${piece.position.join(',')}`} piece={piece} projection={projection} /> })),
    ...diagram.figures.map(figure => ({ depth: figure.position[1], node: <Figure key={`f-${figure.name}`} figure={figure} projection={projection} /> })),
  ].sort((a, b) => a.depth - b.depth);
  const tags = placeTags(diagram.figures.filter(figure => !figure.extra).map(figure => ({ name: figure.name, color: figure.color, head: headOf(figure, projection) })));
  const named = series.colors.filter(item => diagram.figures.some(figure => figure.name === item.name && !figure.extra));
  const strikes = diagram.strikes ?? [];
  const effects = diagram.effects ?? [];
  const distances = diagram.distances ?? [];
  const acting = diagram.figures.filter(figure => figure.acts?.length);
  // One metre of floor width on the picture: the scale bar.
  const metre = projection.scale;
  return (
    <svg
      ref={svgRef} className="desk-diagram__picture" xmlns="http://www.w3.org/2000/svg" viewBox={`0 0 ${DIAGRAM_WIDTH} ${DIAGRAM_HEIGHT}`}
      width={DIAGRAM_WIDTH} height={DIAGRAM_HEIGHT} role="img" aria-label={`${diagram.title}：${diagram.figures.filter(figure => !figure.extra).map(figure => figure.name).join('、')}`}
    >
      <rect width={DIAGRAM_WIDTH} height={DIAGRAM_HEIGHT} fill={PAPER} />
      <polygon points={polygon(floor)} fill="#FAFAF6" stroke={GRID_MAJOR} strokeWidth={2} />
      {lines.map((line, index) => (
        <line key={index} x1={line.from[0]} y1={line.from[1]} x2={line.to[0]} y2={line.to[1]} stroke={line.major ? GRID_MAJOR : GRID} strokeWidth={line.major ? 2 : 1} />
      ))}
      {effects.map(effect => <EffectRings key={effect.id} effect={effect} projection={projection} />)}
      {diagram.cameras.map(camera => <Lens key={camera.id} camera={camera} projection={projection} />)}
      {distances.map(distance => <Ruler key={`d-${distance.a}-${distance.b}`} distance={distance} projection={projection} />)}
      {diagram.routes.map(route => {
        const points = route.points.map(([x, z]) => projection.at(x, z));
        const start = points[0];
        const end = points[points.length - 1];
        const middle = routeMidpoint(points);
        return (
          <g key={`r-${route.name}`}>
            <path d={pathOf(points)} fill="none" stroke={route.color} strokeWidth={5} strokeDasharray="14 10" strokeLinecap="round" />
            <polygon points={polygon(arrowHead(points[points.length - 2], end))} fill={route.color} />
            <circle cx={start[0]} cy={start[1]} r={11} fill={PAPER} stroke={route.color} strokeWidth={4} />
            <circle cx={end[0]} cy={end[1]} r={17} fill="none" stroke={route.color} strokeWidth={2} opacity={0.6} />
            <circle cx={middle[0]} cy={middle[1]} r={15} fill="#FFFFFF" stroke={route.color} strokeWidth={3} />
            <text x={middle[0]} y={middle[1] + 6.5} textAnchor="middle" fontSize={19} fontWeight={700} fill={route.color} fontFamily={FONT}>{route.order}</text>
            {route.label && <text x={middle[0] + 22} y={middle[1] + 6} fontSize={17} fontWeight={700} fill={darker(route.color, 0.3)} fontFamily={FONT}>{route.label}</text>}
          </g>
        );
      })}
      {strikes.map((strike, index) => <StrikeLine key={`s-${index}`} strike={strike} projection={projection} />)}
      {solids.map(item => item.node)}
      {strikes.map((strike, index) => {
        const from = projection.at(strike.from[0], strike.from[1]);
        const to = projection.at(strike.to[0], strike.to[1]);
        return (
          <g key={`sc-${index}`}>
            <polygon points={polygon(contactStar(to))} fill="#FFFFFF" stroke={darker(strike.color, 0.2)} strokeWidth={2.5} />
            <Pill at={((point: Point): Point => [point[0], point[1] - 24])(between(from, to, 0.45))} text={strike.target ? `${strike.short} ${metresLabel(strike.meters)}` : strike.short} color={strike.color} />
          </g>
        );
      })}
      {distances.map(distance => (
        <Pill
          key={`dl-${distance.a}-${distance.b}`} color={INK} size={16} text={metresLabel(distance.meters)}
          at={((point: Point): Point => [point[0], point[1] + 26])(between(projection.at(distance.from[0], distance.from[1]), projection.at(distance.to[0], distance.to[1])))}
        />
      ))}
      {effects.map(effect => {
        // On the near edge of the range: name tags hang above the heads, so the far edge is theirs.
        const near = projection.at(effect.center[0], effect.center[1] + effect.radius_m);
        return <Pill key={`el-${effect.id}`} at={[near[0], near[1] + 16]} text={`${effect.id} ${effect.name}`} color={effect.color} />;
      })}
      {acting.map(figure => {
        const feet = projection.at(figure.position[0], figure.position[1]);
        return <Pill key={`a-${figure.name}`} at={[feet[0], feet[1] + 34]} text={(figure.acts ?? []).join('·')} color={figure.color} size={16} />;
      })}
      {tags.map(tag => (
        <g key={`t-${tag.name}`}>
          <line x1={tag.anchor[0]} y1={tag.anchor[1]} x2={tag.x + tag.width / 2} y2={tag.y + tag.height} stroke={tag.color} strokeWidth={2} />
          <circle cx={tag.anchor[0]} cy={tag.anchor[1]} r={4} fill={tag.color} />
          <rect x={tag.x} y={tag.y} width={tag.width} height={tag.height} rx={6} fill="#FFFFFF" fillOpacity={0.94} stroke={tag.color} strokeWidth={3} />
          <text x={tag.x + tag.width / 2} y={tag.y + 28.5} textAnchor="middle" fontSize={24} fontWeight={700} fill={darker(tag.color, 0.25)} fontFamily={FONT}>{tag.name}</text>
        </g>
      ))}
      <text x={40} y={56} fontSize={32} fontWeight={700} fill={INK} fontFamily={FONT}>{diagram.title}</text>
      {series.location && <text x={DIAGRAM_WIDTH - 40} y={56} textAnchor="end" fontSize={24} fill="#5A5A5A" fontFamily={FONT}>{series.location}</text>}
      <g aria-hidden="true">
        <line x1={40} y1={DIAGRAM_HEIGHT - 66} x2={40 + metre} y2={DIAGRAM_HEIGHT - 66} stroke={INK} strokeWidth={3} />
        <line x1={40} y1={DIAGRAM_HEIGHT - 74} x2={40} y2={DIAGRAM_HEIGHT - 58} stroke={INK} strokeWidth={3} />
        <line x1={40 + metre} y1={DIAGRAM_HEIGHT - 74} x2={40 + metre} y2={DIAGRAM_HEIGHT - 58} stroke={INK} strokeWidth={3} />
        <text x={40 + metre + 10} y={DIAGRAM_HEIGHT - 59} fontSize={18} fontWeight={700} fill={INK} fontFamily={FONT}>1 米</text>
      </g>
      <text x={40} y={DIAGRAM_HEIGHT - 28} fontSize={20} fill="#5A5A5A" fontFamily={FONT}>
        {`每格 ${series.grid.cell_m} 米 · 粗线每 ${series.grid.major_every} 米 · 尖角是人物朝向 · 扇形是镜头水平视野${strikes.length ? ' · 点线是出手方向，星形是接触点' : ''}${effects.length ? ' · 圆圈是特效占位' : ''}`}
      </text>
      {named.map((item, index) => {
        const x = DIAGRAM_WIDTH - 40 - (named.length - index) * 132;
        return (
          <g key={`c-${item.name}`}>
            <circle cx={x + 10} cy={DIAGRAM_HEIGHT - 35} r={9} fill={item.hex} />
            <text x={x + 26} y={DIAGRAM_HEIGHT - 28} fontSize={20} fill={INK} fontFamily={FONT}>{item.name.length > 4 ? `${item.name.slice(0, 4)}…` : item.name}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** Rasterise the drawn SVG; the picture carries its own fonts and colours, so nothing of the page leaks in. */
async function pngOf(svg: SVGSVGElement, pixelRatio = 2): Promise<Blob> {
  const source = new XMLSerializer().serializeToString(svg);
  const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }));
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error('站位图没有画出来，请重试。'));
      image.src = url;
    });
    const canvas = document.createElement('canvas');
    canvas.width = DIAGRAM_WIDTH * pixelRatio;
    canvas.height = DIAGRAM_HEIGHT * pixelRatio;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('这个浏览器不能导出图片。');
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(blob => (blob ? resolve(blob) : reject(new Error('站位图导出失败，请重试。'))), 'image/png');
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function BlockingDiagramDialog({ taskId, sceneId, saving, onClose }: {
  taskId: string; sceneId: string;
  /** The desk still has edits on their way to the server: the diagram may be one step behind. */
  saving: boolean;
  onClose: () => void;
}) {
  const [view, setView] = useState('');
  const [series, setSeries] = useState<BlockingDiagramSeries | null>(null);
  const [error, setError] = useState('');
  const [at, setAt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const pictures = useRef(new Map<number, SVGSVGElement>());
  useEscapeToClose(true, onClose);

  useEffect(() => {
    const controller = new AbortController();
    fetchBlockingDiagrams(taskId, sceneId, view, controller.signal)
      .then(data => { setSeries(data); setError(''); setAt(index => Math.min(index, Math.max(0, data.diagrams.length - 1))); })
      .catch(reason => {
        if (controller.signal.aborted) return;
        setError(reason instanceof ApiError && reason.message ? reason.message : '站位图没有读出来，请稍后重试。');
      });
    return () => controller.abort();
  }, [sceneId, taskId, view]);

  const diagram = series?.diagrams[at] ?? null;
  const shownView = series?.views.find(item => item.id === (view || series.view)) ?? null;
  const tilt = shownView?.tilt_deg ?? 45;

  const download = async (indexes: number[]) => {
    if (!series || busy) return;
    setBusy(true);
    setNotice('');
    try {
      for (const index of indexes) {
        const svg = pictures.current.get(index);
        if (!svg) continue;
        save(await pngOf(svg), diagramFileName(series.scene_id, series.diagrams[index], shownView?.id ?? series.view));
      }
      setNotice(indexes.length > 1 ? `已导出 ${indexes.length} 张站位图，文件在浏览器的下载里。` : '已导出这张站位图，文件在浏览器的下载里。');
    } catch (reason) {
      setNotice(reason instanceof Error && reason.message ? reason.message : '站位图导出失败，请重试。');
    } finally {
      setBusy(false);
    }
  };

  const copyLegend = async () => {
    if (!diagram?.legend?.length) return;
    try {
      await navigator.clipboard.writeText(legendText(diagram.legend));
      setNotice('已复制这张图的标注表，可以贴到表格或备注里，和导出的图放在一起。');
    } catch {
      setNotice('浏览器没有允许复制，请直接在下面的标注表里选中复制。');
    }
  };

  const copyPrompt = async () => {
    if (!diagram) return;
    try {
      await navigator.clipboard.writeText(diagram.prompt);
      setNotice('已复制这张图的提示词，可以交给出图模型画成白模站位图。');
    } catch {
      setNotice('浏览器没有允许复制，请在下面的文字框里手动全选复制。');
    }
  };

  return (
    <div className="desk-modal__backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="desk-modal desk-diagram" role="dialog" aria-modal="true" aria-labelledby="desk-diagram-title">
        <header>
          <h2 id="desk-diagram-title">白模站位图</h2>
          <button type="button" className="desk-icon" aria-label="关闭" title="关闭（Esc）" onClick={onClose}><X aria-hidden="true" /></button>
        </header>
        <p className="desk-modal__note">
          把这一场的调度画成一组站位图：谁站哪、朝哪、怎么走、机器架在哪、能拍到多宽。站位没变的连续几镜合成一张，有人走位或镜头移动的一镜单独一张。
          有打斗或特效的镜头，图上再标出出手方向与接触点、受力方向、特效占位范围和关键距离。特效的位置和范围在右侧「属性」页底部的「特效占位」里手动放。这张带标注的图是给人看的；给视频模型当参考的是导演台里从机位拍下的白模画面，那上面没有任何标注。
          {saving ? ' 导演台还有改动正在保存，图可能差一步，保存好后重新打开。' : ''}
        </p>
        {error && <p className="desk-banner is-warning" role="alert">{error}</p>}
        {!series && !error && <p className="desk-modal__note" role="status">正在读取这一场的调度…</p>}
        {series && diagram && (
          <>
            <div className="desk-diagram__bar">
              <div className="desk-diagram__views" role="radiogroup" aria-label="视角">
                {series.views.map(item => (
                  <button
                    key={item.id} type="button" role="radio" aria-checked={item.id === shownView?.id}
                    className={item.id === shownView?.id ? 'is-active' : ''} onClick={() => setView(item.id)}
                  >{item.label}</button>
                ))}
              </div>
              <div className="desk-diagram__pager">
                <button type="button" className="desk-icon" aria-label="上一张" title="上一张" disabled={at === 0} onClick={() => setAt(at - 1)}><ChevronLeft aria-hidden="true" /></button>
                <span aria-live="polite">{`${at + 1} / ${series.diagrams.length}`}</span>
                <button type="button" className="desk-icon" aria-label="下一张" title="下一张" disabled={at >= series.diagrams.length - 1} onClick={() => setAt(at + 1)}><ChevronRight aria-hidden="true" /></button>
              </div>
              <div className="desk-diagram__actions">
                <button type="button" className="desk-button" disabled={busy} onClick={() => { void download([at]); }}><Download aria-hidden="true" /> 导出这张</button>
                {series.diagrams.length > 1 && (
                  <button type="button" className="desk-button" disabled={busy} onClick={() => { void download(series.diagrams.map((_item, index) => index)); }}>
                    <Download aria-hidden="true" /> {`导出全部 ${series.diagrams.length} 张`}
                  </button>
                )}
              </div>
            </div>
            <div className="desk-diagram__stage">
              {series.diagrams.map((item, index) => (
                <div key={item.index} className="desk-diagram__sheet" hidden={index !== at}>
                  <DiagramPicture
                    diagram={item} series={series} tiltDeg={tilt}
                    svgRef={node => { if (node) pictures.current.set(index, node); else pictures.current.delete(index); }}
                  />
                </div>
              ))}
            </div>
            <ul className="desk-diagram__notes">
              {diagram.notes.map(note => <li key={note}>{note}</li>)}
              {!series.persisted && <li>这一场的调度还没有保存过，图按预览方案画。</li>}
            </ul>
            {!!diagram.legend?.length && (
              <details className="desk-diagram__legend">
                <summary>{`标注表（图上的 ${diagram.legend.length} 个标记各是什么）`}</summary>
                <table>
                  <thead><tr><th scope="col">标记</th><th scope="col">含义</th><th scope="col">颜色</th><th scope="col">指向位置</th></tr></thead>
                  <tbody>
                    {diagram.legend.map((row, index) => (
                      <tr key={`${row.mark}-${index}`}><th scope="row">{row.mark}</th><td>{row.meaning}</td><td>{row.color}</td><td>{row.where || '—'}</td></tr>
                    ))}
                  </tbody>
                </table>
                {!!diagram.nodes?.length && (
                  <>
                    <h3>动作节点</h3>
                    <ol>
                      {diagram.nodes.map((node, index) => (
                        <li key={index}>
                          {`第 ${node.shot_id} 镜${node.at_s === null ? '' : ` ${node.at_s}–${node.end_s ?? node.at_s} 秒`} · ${node.name}：${node.what}${node.source === 'text' ? '（按分镜文字）' : ''}`}
                        </li>
                      ))}
                    </ol>
                  </>
                )}
                <button type="button" className="desk-button" onClick={() => { void copyLegend(); }}><Copy aria-hidden="true" /> 复制标注表</button>
              </details>
            )}
            <details className="desk-diagram__prompt">
              <summary>这张图的出图提示词（可交给出图模型画成 3D 白模站位图）</summary>
              <textarea readOnly rows={10} value={diagram.prompt} aria-label="这张站位图的出图提示词" onFocus={event => event.currentTarget.select()} />
              <button type="button" className="desk-button" onClick={() => { void copyPrompt(); }}><Copy aria-hidden="true" /> 复制提示词</button>
            </details>
            {notice && <p className="desk-modal__note" role="status">{notice}</p>}
          </>
        )}
      </section>
    </div>
  );
}
