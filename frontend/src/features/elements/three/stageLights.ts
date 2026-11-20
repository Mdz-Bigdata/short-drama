/**
 * 3D 资产台的灯。主光和补光是中性白，模型的颜色才对得上它的参考图；
 * 只有背后一盏很淡的轮廓光带品牌色。全是平行光：不随距离衰减，一只茶杯和一条街受光一样。
 */
export interface StageLight {
  position: [number, number, number];
  intensity: number;
  /** 不写就是白光。 */
  color?: string;
}

export const STAGE_LIGHTS: { key: StageLight; fill: StageLight; rim: StageLight } = {
  key: { position: [5, 8, 4], intensity: 2 },
  fill: { position: [-6, 3, 2], intensity: 0.5 },
  rim: { position: [-2, 4, -6], intensity: 0.6, color: '#f0a3b4' },
};

export const STAGE_AMBIENT = { intensity: 0.3, sky: '#ffffff', ground: '#77757a', hemisphere: 0.6 };

/** 环境贴图里的一块白色灯板：朝向原点，金属和光滑表面靠反射它们才不发黑。 */
export interface StagePanel {
  position: [number, number, number];
  size: [number, number];
  intensity: number;
}

export const STAGE_PANELS: StagePanel[] = [
  { position: [0, 6, 0], size: [10, 10], intensity: 1.5 },
  { position: [-7, 2, 3], size: [6, 8], intensity: 1.2 },
  { position: [7, 3, -2], size: [5, 7], intensity: 0.9 },
  { position: [0, 2, -8], size: [10, 4], intensity: 0.6 },
];

/** 灯板之外的环境底色：中性灰，给暗部一点底光，也让金属不至于反射出纯黑。 */
export const STAGE_SURROUND = '#6f6e72';
