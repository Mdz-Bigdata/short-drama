import type { GuideSettings } from '../deskTypes';
import { centerCross, fitFrame, letterboxBars, parseAspectRatio, safeFrame, thirdsLines } from './compositionGeometry';

// The lens canvas already has the delivery aspect, so the overlay can work in a nominal
// coordinate space of that shape and let the SVG stretch to the canvas: no measuring, no resize
// observer, and the guides can never drift off the picture.
const NOMINAL_WIDTH = 1000;

export function CompositionGuides({ deliveryAspect, guides }: { deliveryAspect: number; guides: GuideSettings }) {
  const viewWidth = NOMINAL_WIDTH;
  const viewHeight = NOMINAL_WIDTH / deliveryAspect;
  const aspect = (guides.aspect && parseAspectRatio(guides.aspect)) || deliveryAspect;
  const frame = fitFrame(viewWidth, viewHeight, aspect);
  const bars = guides.frame ? letterboxBars(viewWidth, viewHeight, frame) : [];
  const safe = safeFrame(frame);
  return (
    <svg className="desk-guides" viewBox={`0 0 ${viewWidth} ${viewHeight}`} preserveAspectRatio="none" role="img" aria-label="构图辅助线">
      {bars.map((bar, index) => <rect key={index} className="desk-guides__mask" data-guide="mask" x={bar.x} y={bar.y} width={bar.width} height={bar.height} />)}
      {guides.frame && <rect className="desk-guides__frame" data-guide="frame" x={frame.x} y={frame.y} width={frame.width} height={frame.height} />}
      {guides.thirds && thirdsLines(frame).map((line, index) => <line key={index} className="desk-guides__line" data-guide="thirds" {...line} />)}
      {guides.safe && <rect className="desk-guides__safe" data-guide="safe" x={safe.x} y={safe.y} width={safe.width} height={safe.height} />}
      {guides.cross && centerCross(frame).map((line, index) => <line key={index} className="desk-guides__line is-cross" data-guide="cross" {...line} />)}
    </svg>
  );
}
