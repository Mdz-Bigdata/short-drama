import { actorSheetCellLabels } from './assetTabLabels';
import type { CharacterDashboardCharacter, CharacterViewContract } from './types';

/** 身份选择器里的一个视图：五个身份锚点之一，或设定集里的右侧 45° 侧脸格。 */
export interface IdentityDisplayView {
  key: string;
  order: number;
  angleDegrees: number;
  labelZh: string;
  labelEn: string;
  imageUrl: string | null;
  /** 不是模型画的，而是从别的格子补出来的(右侧 45° 由左侧 45° 水平翻转)。 */
  derivedFrom: string | null;
}

/** 选择器的展示顺序：先三张脸(正脸、左 45°、右 45°)，再三张全身(正面、侧面 90°、背面 180°)。 */
const DISPLAY_ORDER = ['face_front', 'face_three_quarter', 'face_three_quarter_right', 'front', 'profile', 'back'] as const;

const RIGHT_FACE = {
  key: 'face_three_quarter_right',
  angleDegrees: 45,
  labelZh: actorSheetCellLabels.face_three_quarter_right,
  labelEn: 'Face right 45°',
};

/**
 * 六个身份视图。旧五视图记录(契约里没有正脸锚点)原样沿用契约的五个角度，不凭空加第六格。
 */
export function identityDisplayViews(
  character: CharacterDashboardCharacter,
  contract: CharacterViewContract,
): IdentityDisplayView[] {
  const urlOf = (key: string) => {
    const asset = character.views.find(view => view.key === key);
    return asset?.available && asset.imageUrl ? asset.imageUrl : null;
  };
  if (!contract.views.some(view => view.key === 'face_front')) {
    return contract.views.map(view => ({
      key: view.key, order: view.order, angleDegrees: view.angleDegrees,
      labelZh: view.labelZh, labelEn: view.labelEn, imageUrl: urlOf(view.key), derivedFrom: null,
    }));
  }
  const rightCell = character.sheetCells.find(cell => cell.key === 'face_three_quarter_right');
  return DISPLAY_ORDER.map((key, index) => {
    if (key === 'face_three_quarter_right') {
      return {
        ...RIGHT_FACE,
        order: index + 1,
        imageUrl: rightCell?.available && rightCell.imageUrl ? rightCell.imageUrl : null,
        derivedFrom: rightCell?.derivedFrom ?? null,
      };
    }
    const definition = contract.views.find(view => view.key === key);
    return {
      key,
      order: index + 1,
      angleDegrees: definition?.angleDegrees ?? 0,
      labelZh: definition?.labelZh ?? key,
      labelEn: definition?.labelEn ?? key,
      imageUrl: urlOf(key),
      derivedFrom: null,
    };
  });
}
