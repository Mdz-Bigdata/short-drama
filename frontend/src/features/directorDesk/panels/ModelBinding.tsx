import { useCallback, useEffect, useRef, useState } from 'react';
import { Boxes, Link2Off, Upload } from 'lucide-react';

import type { StageLandmark } from '../../spatial/spatialTypes';
import type { EditRequest } from '../deskTypes';
import { importModelElement, listModelElements, modelRefusal, type ElementModelChoice } from '../elementLibraryApi';

interface Props {
  taskId: string;
  landmark: StageLandmark;
  editable: boolean;
  onCommit: (request: EditRequest) => void;
}

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * Bind a set piece to a model in the element library, so the stage shows the real thing instead of
 * a box. The plan keeps the element's id and nothing else: the file itself stays in the library,
 * under the person's account, where it can be replaced without the stage knowing.
 */
export function ModelBinding({ taskId, landmark, editable, onCommit }: Props) {
  const [choices, setChoices] = useState<ElementModelChoice[]>([]);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const refresh = useCallback((signal?: AbortSignal) => (
    listModelElements(taskId, signal)
      .then(setChoices)
      .catch(error => { if (!signal?.aborted) setNotice(messageOf(error, '元素库读取失败。')); })
  ), [taskId]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const bound = landmark.element_id || '';
  const current = choices.find(item => item.id === bound);
  const bind = (elementId: string, label: string) => onCommit({
    label, operations: [{ op: 'bind_landmark_model', name: landmark.name, element_id: elementId }],
  });

  const importFile = (chosen: File | undefined) => {
    if (!chosen || busy) return;
    const refusal = modelRefusal(chosen);
    if (refusal) { setNotice(refusal); return; }
    setBusy(true);
    setNotice('');
    void (async () => {
      try {
        const created = await importModelElement(taskId, chosen.name.replace(/\.glb$/i, '').slice(0, 60) || landmark.name, 'prop', chosen);
        await refresh();
        bind(created.id, `为 ${landmark.name} 导入模型`);
        setNotice(`已导入「${created.name}」并绑定到 ${landmark.name}。`);
      } catch (error) {
        // The server's own sentence: it is the one that knows the size and triangle caps.
        setNotice(messageOf(error, '模型导入失败。'));
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <section className="desk-binding" aria-label="绑定模型">
      <h3><Boxes aria-hidden="true" /> 绑定模型</h3>
      <label className="desk-field is-wide">
        <span>元素库模型</span>
        <select
          aria-label="绑定模型" value={bound} disabled={!editable || busy}
          onChange={event => bind(event.target.value, event.target.value ? `为 ${landmark.name} 绑定模型` : `解除 ${landmark.name} 的模型`)}
        >
          <option value="">不绑定，使用基本形状</option>
          {choices.map(item => <option key={item.id} value={item.id}>{item.kind === 'scene' ? '场景' : '道具'} · {item.name}</option>)}
          {/* A binding whose element is gone from this project still shows, so it can be undone. */}
          {bound && !current && <option value={bound}>已绑定（{bound.slice(0, 8)}，不在本项目列表中）</option>}
        </select>
      </label>
      {choices.length === 0 && <p className="desk-inspector__empty">本项目的元素库里还没有带 GLB 的道具或场景。可以直接从下面导入一个。</p>}
      {bound && (
        <button type="button" className="desk-button" disabled={!editable || busy} onClick={() => bind('', `解除 ${landmark.name} 的模型`)}>
          <Link2Off aria-hidden="true" /> 解除绑定
        </button>
      )}
      <button type="button" className="desk-button" disabled={!editable || busy} onClick={() => file.current?.click()}>
        <Upload aria-hidden="true" /> {busy ? '导入中…' : '导入本地 GLB/GLTF'}
      </button>
      <input
        ref={file} type="file" accept=".glb,model/gltf-binary" hidden aria-label="导入本地 GLB 文件"
        onChange={event => { const chosen = event.target.files?.[0]; event.target.value = ''; importFile(chosen); }}
      />
      <p className="desk-captures__note">模型会存进元素库（道具），不超过 25 MB、100 万三角面；导入后自动绑定到本件。模型按本件的宽/深/高等比缩放并落到地面。</p>
      {notice && <p className="desk-captures__notice" role="status">{notice}</p>}
    </section>
  );
}
