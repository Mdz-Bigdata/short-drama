"""Motivation-first acting plan adapted cleanly from observable-performance principles."""

from __future__ import annotations

from app.schema.advanced import PerformanceBeat, PerformancePlan, PerformancePlanRequest


class PerformancePlanner:
    _PHASES = (
        (
            "trigger", 0.00, 0.14,
            "视线先落到触发物，不提前看向结果", "吸气突然变浅，呼吸在触发点短暂停住",
            "眼睑轻停、眉间出现极小收紧，不做夸张表情", "正在进行的手部动作先停住，身体重心不突变",
            "不开口，保留可读的反应停顿", "先保留触发原因与人物反应的空间关系",
        ),
        (
            "contain", 0.14, 0.34,
            "视线仍停在触发物，随后短暂避开对方", "缓慢恢复鼻息，避免戏剧化喘气",
            "嘴角原有张力减弱但尚未完全消失", "手指轻收，肩颈保持克制而非僵硬",
            "开口前停顿半拍，重音先压住", "中景同时读取手部、姿态和脸部变化",
        ),
        (
            "leak", 0.34, 0.55,
            "视线出现一次不完全受控的回看", "呼气略长于吸气，句前可见轻微换气",
            "眉心与下眼睑短暂泄露真实情绪，左右脸保持自然不对称", "指尖摩擦或握持力度发生一次可观察变化",
            "语速略慢、音量不突然抬高，关键词前留短停顿", "缓慢推近，但不切断触发物与反应的因果",
        ),
        (
            "decision", 0.55, 0.78,
            "视线从触发物移向对手或明确目标", "完成一次受控吸气后再说话",
            "表情收束为角色主动选择的外在面具", "躯干重新立稳，手部完成唯一关键动作",
            "说出台词，重音与权力转移对齐，句中停顿不机械", "近景承接权力变化并保留自然口型",
        ),
        (
            "release", 0.78, 1.00,
            "台词结束后视线不立刻游移，给对方反应空间", "收音后自然呼气，不在句尾突然憋停",
            "面部只残留细微余波，不回弹成中性模板脸", "动作完成后手离开道具，姿态形成下一镜可接状态",
            "句尾情绪延迟半拍释放，保留收音与沉默", "停留反应把，形成可剪辑的尾部手柄",
        ),
    )

    def build(self, request: PerformancePlanRequest) -> PerformancePlan:
        duration = request.duration_seconds
        beats = [
            PerformanceBeat(
                phase=phase,
                start_seconds=round(duration * start, 3),
                end_seconds=round(duration * end, 3),
                gaze=gaze,
                breath=breath,
                face=face,
                body=body,
                voice=(voice + (f"；对白原文仅为{{{request.dialogue}}}" if request.dialogue and phase == "decision" else "")),
                camera_support=camera,
            )
            for phase, start, end, gaze, breath, face, body, voice, camera in self._PHASES
        ]
        return PerformancePlan(
            character=request.character,
            motivation=request.motivation,
            trigger=request.trigger,
            emotion_arc=f"{request.start_emotion} → {request.end_emotion}",
            power_shift=request.power_shift or "保持输入中的关系，不擅自增加权力变化",
            beats=beats,
            identity_constraints=[
                "全过程不改变身份、年龄、五官几何、发型、服装、配饰和身体比例。",
                "眨眼、呼吸、口型与微表情保持真人幅度，左右脸允许细微自然不对称。",
                "动作遵守上一镜结束态、视线、道具归属和摄影轴线。",
            ],
            negative_constraints=[
                "不使用夸张眉飞色舞、塑料皮肤、僵硬凝视、无动机抽搐或模板化哭笑。",
                "不编造输入中不存在的台词、创伤、关系或剧情结果。",
            ],
        )
