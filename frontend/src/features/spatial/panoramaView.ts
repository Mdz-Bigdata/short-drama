/** Where a person is looking inside the panorama sphere; dragging moves these, and pitch stops short of the poles. */
export interface LookAngles {
  yaw: number;
  pitch: number;
}

const MAX_PITCH = 85;
// Degrees of turn per pixel dragged: slow enough to look around, the picture follows the hand.
const DRAG_SPEED = 0.2;

export function dragLook(look: LookAngles, dx: number, dy: number): LookAngles {
  return {
    yaw: look.yaw - dx * DRAG_SPEED,
    pitch: Math.max(-MAX_PITCH, Math.min(MAX_PITCH, look.pitch + dy * DRAG_SPEED)),
  };
}

export function lookTarget({ yaw, pitch }: LookAngles): [number, number, number] {
  const phi = (pitch * Math.PI) / 180;
  const theta = (yaw * Math.PI) / 180;
  return [Math.cos(phi) * Math.sin(theta), Math.sin(phi), -Math.cos(phi) * Math.cos(theta)];
}
