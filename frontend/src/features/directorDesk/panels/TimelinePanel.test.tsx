// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { ActorKey, CameraKey, StagePlan } from '../../spatial/spatialTypes';
import type { EditRequest, SelectionRef } from '../deskTypes';
import type { DeskPlayback } from '../useDeskPlayback';
import { TimelinePanel } from './TimelinePanel';

const CAMERA: CameraKey[] = [
  { time: 0, position: [0, 1.45, 5.2], target: [0, 0.9, 0], lens_mm: 28, easing: 'linear' },
  { time: 2, position: [0, 1.45, 3.2], target: [0, 0.9, 0], lens_mm: 28, easing: 'smooth' },
];
const WALK: ActorKey[] = [{ time: 0, position: [-1.3, 0], yaw_deg: 90, easing: 'linear' }, { time: 3.5, position: [1, 1], yaw_deg: 0, easing: 'smooth' }];
const TIMED: StagePlan = { ...PLAN, timelines: { 1: { duration_s: 4, fps: 24, camera: CAMERA, actors: { 林夏: WALK } } } };

function playbackAt(time: number, fps = 24, playing = false): DeskPlayback {
  return {
    time, frame: Math.round(time * fps), playing, loop: false,
    play: vi.fn(), pause: vi.fn(), stop: vi.fn(), seek: vi.fn(), step: vi.fn(), setLoop: vi.fn(),
  };
}

describe('TimelinePanel', () => {
  const onCommit = vi.fn<(request: EditRequest) => void>();
  const onSelect = vi.fn();
  const show = (plan: StagePlan, playback: DeskPlayback, selection: SelectionRef[] = [], editable = true) => render(
    <TimelinePanel plan={plan} shot={plan.shots[0]} playback={playback} selection={selection} editable={editable} collapsed={false} onCollapsed={() => {}} onCommit={onCommit} onSelect={onSelect} />,
  );
  const lastOperations = () => onCommit.mock.calls[onCommit.mock.calls.length - 1][0].operations;

  afterEach(() => {
    cleanup();
    onCommit.mockReset();
    onSelect.mockReset();
  });

  it('shows the transport, the timecode and one track per keyed or selected actor', async () => {
    const playback = playbackAt(1.5);
    show(TIMED, playback, [{ kind: 'actor', name: '周教授' }]);
    expect(screen.getByLabelText('时间码').textContent).toBe('00:01:12');
    expect(screen.getByText('第 37 / 96 帧')).toBeTruthy();
    expect(screen.getByLabelText('机位轨')).toBeTruthy();
    expect(screen.getByLabelText('「林夏」轨')).toBeTruthy();
    expect(screen.getByLabelText('「周教授」轨')).toBeTruthy();
    expect(screen.queryByLabelText('「助手」轨')).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: '播放' }));
    await userEvent.click(screen.getByRole('button', { name: '下一帧' }));
    await userEvent.click(screen.getByRole('button', { name: '上一帧' }));
    await userEvent.click(screen.getByRole('button', { name: '停止' }));
    await userEvent.click(screen.getByRole('button', { name: '循环播放' }));
    expect(playback.play).toHaveBeenCalled();
    expect((playback.step as ReturnType<typeof vi.fn>).mock.calls).toEqual([[1], [-1]]);
    expect(playback.stop).toHaveBeenCalled();
    expect(playback.setLoop).toHaveBeenCalledWith(true);

    await userEvent.click(screen.getByRole('button', { name: '林夏' }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'actor', name: '林夏' }, false);
  });

  it('keys the lens at the playhead with the pose it has at that instant', async () => {
    show(TIMED, playbackAt(1));
    await userEvent.click(screen.getByRole('button', { name: /在播放头处打关键帧 · 机位/ }));
    expect(onCommit.mock.calls[0][0].label).toBe('机位关键帧');
    expect(lastOperations()).toEqual([{
      op: 'set_timeline', shot_id: 1,
      camera: [CAMERA[0], { time: 1, position: [0, 1.45, 4.2], target: [0, 0.9, 0], lens_mm: 28, easing: 'smooth' }, CAMERA[1]],
    }]);
  });

  it('turns a storyboard move into real keys the first time the lens is keyed', async () => {
    render(<TimelinePanel plan={PLAN} shot={PLAN.shots[1]} playback={playbackAt(0)} selection={[]} editable collapsed={false} onCollapsed={() => {}} onCommit={onCommit} onSelect={onSelect} />);
    expect(screen.getByText('· 分镜运镜')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /在播放头处打关键帧 · 机位/ }));
    const keys = lastOperations()[0].camera as CameraKey[];
    expect(keys.map(key => key.time)).toEqual([0, 5]);
    expect(keys[1].position).toEqual([-0.2, 1.55, 0.65]);
  });

  it('keys the selected actor as a whole figure: place, facing and pose', async () => {
    const posed: StagePlan = { ...PLAN, actors: PLAN.actors.map(actor => (actor.name === '周教授' ? { ...actor, figure: 'mannequin', pose: { preset: 'walk', joints: {}, clip: '', clip_phase: 0 } } : actor)) };
    show(posed, playbackAt(0.5), [{ kind: 'actor', name: '周教授' }]);
    await userEvent.click(screen.getByRole('button', { name: /在播放头处打关键帧 · 周教授/ }));
    expect(lastOperations()).toEqual([{
      op: 'set_timeline', shot_id: 1,
      actors: { 周教授: [{ time: 0.5, position: [1.3, 0], yaw_deg: -90, pose: { preset: 'walk', joints: {}, clip: '', clip_phase: 0 }, easing: 'smooth' }] },
    }]);
  });

  it('needs an actor selected before it can key one', () => {
    show(TIMED, playbackAt(0));
    expect((screen.getByRole('button', { name: /在播放头处打关键帧 · 角色/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('selects a key on click and jumps to it, then changes its easing, copies, pastes and deletes', async () => {
    const playback = playbackAt(3);
    show(TIMED, playback);
    const key = screen.getByRole('button', { name: '机位关键帧 2.00 秒' });
    fireEvent.pointerDown(key, { clientX: 500, pointerId: 1 });
    fireEvent.pointerUp(key, { clientX: 500, pointerId: 1 });
    expect(playback.seek).toHaveBeenCalledWith(2);
    expect(key.getAttribute('aria-pressed')).toBe('true');

    await userEvent.selectOptions(screen.getByLabelText('关键帧缓动'), 'whip');
    expect(lastOperations()).toEqual([{ op: 'set_timeline', shot_id: 1, camera: [CAMERA[0], { ...CAMERA[1], easing: 'whip' }] }]);

    await userEvent.click(screen.getByRole('button', { name: '复制关键帧' }));
    await userEvent.click(screen.getByRole('button', { name: '在播放头处粘贴关键帧' }));
    expect(lastOperations()).toEqual([{ op: 'set_timeline', shot_id: 1, camera: [...CAMERA, { ...CAMERA[1], time: 3 }] }]);

    // The paste moved the selection to the new key; the third key is not in this plan, so pick the second again.
    fireEvent.pointerDown(key, { clientX: 500, pointerId: 1 });
    fireEvent.pointerUp(key, { clientX: 500, pointerId: 1 });
    await userEvent.click(screen.getByRole('button', { name: '删除关键帧' }));
    expect(lastOperations()).toEqual([{ op: 'set_timeline', shot_id: 1, camera: [CAMERA[0]] }]);
  });

  it('drags a key in time, snapped to frames, and writes once on release', () => {
    show(TIMED, playbackAt(0));
    const lane = screen.getByLabelText('「林夏」轨');
    vi.spyOn(lane, 'getBoundingClientRect').mockReturnValue({ left: 100, width: 960, top: 0, height: 20, right: 1060, bottom: 20, x: 100, y: 0, toJSON: () => ({}) });
    const key = within(lane).getByRole('button', { name: '「林夏」关键帧 3.50 秒' });
    fireEvent.pointerDown(key, { clientX: 940, pointerId: 1 });
    fireEvent.pointerMove(key, { clientX: 705, pointerId: 1 });     // 2.5208 s → frame 61 → 2.542 s
    expect(onCommit).not.toHaveBeenCalled();
    expect(within(lane).getByRole('button', { name: '「林夏」关键帧 2.54 秒' })).toBeTruthy();
    fireEvent.pointerUp(key, { clientX: 705, pointerId: 1 });
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(lastOperations()).toEqual([{ op: 'set_timeline', shot_id: 1, actors: { 林夏: [WALK[0], { ...WALK[1], time: 2.542 }] } }]);
  });

  it('nudges and deletes a focused key from the keyboard', () => {
    show(TIMED, playbackAt(0));
    const key = screen.getByRole('button', { name: '机位关键帧 2.00 秒' });
    fireEvent.keyDown(key, { key: 'ArrowRight' });
    expect((lastOperations()[0].camera as CameraKey[])[1].time).toBe(2.042);
    fireEvent.keyDown(key, { key: 'Delete' });
    expect(lastOperations()).toEqual([{ op: 'set_timeline', shot_id: 1, camera: [CAMERA[0]] }]);
  });

  it('scrubs the playhead from the ruler, on whole frames', () => {
    const playback = playbackAt(0);
    show(TIMED, playback);
    const ruler = screen.getByRole('slider', { name: '播放头' });
    vi.spyOn(ruler, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 960, top: 0, height: 20, right: 960, bottom: 20, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.pointerDown(ruler, { clientX: 300, pointerId: 1 });
    expect(playback.pause).toHaveBeenCalled();
    expect(playback.seek).toHaveBeenCalledWith(30 / 24);
    fireEvent.pointerDown(ruler, { clientX: 5000, pointerId: 1 });
    expect(playback.seek).toHaveBeenLastCalledWith(95 / 24);
  });

  it('lets a number that is still being typed be sent before the playhead leaves the instant it was typed about', () => {
    const order: string[] = [];
    const playback = playbackAt(0);
    (playback.seek as ReturnType<typeof vi.fn>).mockImplementation(() => order.push('seek'));
    show(TIMED, playback);
    const field = document.createElement('input');
    field.addEventListener('blur', () => order.push('blur'));
    document.body.appendChild(field);
    field.focus();
    fireEvent.pointerDown(screen.getByRole('slider', { name: '播放头' }), { clientX: 10, pointerId: 1 });
    expect(order).toEqual(['blur', 'seek']);
    field.remove();
  });

  it('refuses to shrink the shot below its last key, naming the key, and sends a valid duration', () => {
    show(TIMED, playbackAt(0));
    const field = screen.getByLabelText('镜头时长（秒）') as HTMLInputElement;
    fireEvent.change(field, { target: { value: '3' } });
    fireEvent.blur(field);
    expect(screen.getByRole('alert').textContent).toContain('「林夏」轨在 3.50 秒还有一帧');
    expect(onCommit).not.toHaveBeenCalled();
    expect(field.value).toBe('4');

    fireEvent.change(field, { target: { value: '6' } });
    fireEvent.blur(field);
    expect(lastOperations()).toEqual([{ op: 'set_timeline', shot_id: 1, duration_s: 6 }]);
    expect(screen.queryByRole('alert')).toBeNull();

    fireEvent.change(screen.getByLabelText('帧率'), { target: { value: '30' } });
    expect(lastOperations()).toEqual([{ op: 'set_timeline', shot_id: 1, fps: 30 }]);
  });

  it('applies a camera-move preset with only the parameters that mean something for it', async () => {
    show(TIMED, playbackAt(0));
    await userEvent.click(screen.getByRole('button', { name: '运镜预设' }));
    const form = screen.getByRole('form', { name: '运镜预设' });
    expect(within(form).getAllByRole('option').filter(option => (option as HTMLOptionElement).parentElement === within(form).getByLabelText('运镜预设类型'))).toHaveLength(14);
    expect(within(form).queryByLabelText('角度')).toBeNull();
    await userEvent.click(within(form).getByRole('button', { name: '应用到第 1 镜' }));
    expect(onCommit.mock.calls[0][0]).toEqual({ label: '运镜：推近', barrier: true, operations: [{ op: 'apply_camera_move', shot_id: 1, preset: 'push', amplitude: 1 }] });

    await userEvent.click(screen.getByRole('button', { name: '运镜预设' }));
    const again = screen.getByRole('form', { name: '运镜预设' });
    await userEvent.selectOptions(within(again).getByLabelText('运镜预设类型'), 'whip-pan');
    expect((within(again).getByLabelText('角度') as HTMLInputElement).value).toBe('60');
    await userEvent.selectOptions(within(again).getByLabelText('方向'), 'left');
    await userEvent.selectOptions(within(again).getByLabelText('运镜缓动'), 'ease-in');
    fireEvent.change(within(again).getByLabelText('幅度'), { target: { value: '1.5' } });
    await userEvent.click(within(again).getByRole('button', { name: '应用到第 1 镜' }));
    expect(lastOperations()).toEqual([{ op: 'apply_camera_move', shot_id: 1, preset: 'whip-pan', amplitude: 1.5, angle: 60, side: 'left', easing: 'ease-in' }]);
  });

  it('clears the shot’s timeline, and edits nothing when the desk is read-only or playing', async () => {
    const view = show(TIMED, playbackAt(0));
    await userEvent.click(screen.getByRole('button', { name: '清空本镜时间线' }));
    expect(lastOperations()).toEqual([{ op: 'clear_timeline', shot_id: 1 }]);
    view.unmount();

    show(TIMED, playbackAt(1, 24, true), [{ kind: 'actor', name: '林夏' }], false);
    expect((screen.getByRole('button', { name: /打关键帧 · 机位/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '运镜预设' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText('镜头时长（秒）') as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole('button', { name: '暂停' })).toBeTruthy();
  });

  it('collapses to a single line', async () => {
    const onCollapsed = vi.fn();
    render(<TimelinePanel plan={TIMED} shot={TIMED.shots[0]} playback={playbackAt(1)} selection={[]} editable collapsed onCollapsed={onCollapsed} onCommit={onCommit} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole('button', { name: /时间线 · 00:01:00/ }));
    expect(onCollapsed).toHaveBeenCalledWith(false);
  });
});
