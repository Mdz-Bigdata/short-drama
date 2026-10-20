import type { CharacterDashboardCharacter } from './types';

// 模型漏画、切图时从立绘按部位补裁的元素/细节格可以让模型真正补画；右侧 45° 侧脸由高清身份视图负责。
const NOT_FILLABLE = new Set(['face_three_quarter_right']);

export function fillableDetailCount(character: CharacterDashboardCharacter): number {
  return character.sheetCells.filter(cell => cell.available && cell.derivedFrom && !NOT_FILLABLE.has(cell.key)).length;
}

export function confirmDetailFill(character: CharacterDashboardCharacter): boolean {
  const count = fillableDetailCount(character);
  return window.confirm(
    `为「${character.name}」补画 ${count} 个补位细节格？\n以现有设定集为参考出一张特写拼板(超过 8 格出两张)，是一次付费出图；画得合格的格子替换补位裁切，其余保留。`,
  );
}
