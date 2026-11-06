import unittest

from app.core.camera_motion import motion_problem, move_classes


class MotionLintTests(unittest.TestCase):
    def test_one_main_move_with_one_quiet_helper_passes(self):
        self.assertEqual(motion_problem("缓慢推近，带轻微手持呼吸感，落幅停稳"), "")
        self.assertEqual(motion_problem("固定机位"), "")

    def test_pushing_in_then_pulling_back_is_a_conflict(self):
        self.assertIn("对冲", motion_problem("火苗偏斜时极缓推近，熄灭后骤停，随后拉远至中景"))

    def test_three_stacked_moves_are_too_many(self):
        self.assertIn("3种运镜", motion_problem("随侧脸向右微移并轻推，顺势下摇"))

    def test_negations_asides_and_fingerprints_are_not_moves(self):
        self.assertEqual(move_classes("缓慢推近（slow dolly in, pan），不拉回、不左右摇摆 `[指纹：横移]`"), ["推近"])

    def test_a_timed_one_take_is_checked_beat_by_beat(self):
        self.assertEqual(motion_problem("0–2秒跟拍横移，2–4秒拉远至全景，4–6秒缓慢推近"), "")
        self.assertIn("对冲", motion_problem("0–2秒推近又拉远，2–4秒固定"))


class OrbitTests(unittest.TestCase):
    def test_a_full_orbit_breaks_the_axis_and_a_half_orbit_does_not(self):
        self.assertIn("越轴", motion_problem("环绕主体360度"))
        self.assertIn("越轴", motion_problem("绕两人缓慢环绕一周后停在过肩位"))
        self.assertEqual(motion_problem("绕两人缓慢环绕约120度，落幅停在过肩位"), "")
        self.assertEqual(motion_problem("缓慢推近，一周前的回忆"), "")



    def test_a_focus_pull_is_not_the_camera_pulling_back(self):
        self.assertEqual(motion_problem("起幅静止 1 秒后启动，缓慢横摇向右配极缓推近；末两秒焦点由剑鞘拉回前景手部，落幅停稳"), "")
        self.assertEqual(motion_problem("缓慢推近＋轻微右移，推到布面停稳，末段焦点由布面轻移到陈九眼睛再拉回沈无咎的手"), "")
        self.assertEqual(motion_problem("缓慢推近，末段拉回焦点"), "")
        self.assertIn("对冲", motion_problem("缓慢推近至手部，末段焦点落在手上，随后缓慢拉回双人中景"))

    def test_saying_what_a_shot_does_not_do_is_not_doing_it(self):
        self.assertEqual(motion_problem("侧向低机位跟移，随人物前行减速，落幅前二次缓推后收势静止，全程无变焦无甩镜"), "")
        self.assertEqual(move_classes("无人机缓推"), ["推近"])

    def test_a_hand_moving_is_not_the_camera_moving(self):
        self.assertEqual(motion_problem("起幅固定0.8秒，随后随右掌移向木砧缓慢上摇并轻推，落到沈无咎抬眼时停稳"), "")
        self.assertEqual(move_classes("镜头缓慢移向门口"), ["移"])

    def test_three_real_moves_in_a_row_are_still_caught(self):
        self.assertIn("3种运镜", motion_problem("静止起幅→随人物回身向左微横移→缓慢推近至近景→顺势摇向画面右侧→落幅固定"))
        self.assertIn("3种运镜", motion_problem("缓慢推近＋向右横移＋上摇；刀口亮线处略停半拍"))
        self.assertIn("对冲", motion_problem("极缓推近→沿砧面横移三寸→微拉开半尺→落幅静止"))

if __name__ == "__main__":
    unittest.main()
