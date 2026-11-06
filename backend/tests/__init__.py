"""Backend tests for the production pipeline."""

import os

# 高清身份视图会在设定集通过后再发两次出图请求；测试里的网关多数没被替身替换，
# 默认关掉，免得测试去连真实供应商。专门测它的用例自己把开关打开。
os.environ.setdefault("CHARACTER_HD_VIEWS", "0")
os.environ.setdefault("CHARACTER_DETAIL_FILL", "0")
# 自然语言转工具助手会调用文本模型：测试默认关掉，专门测它的用例自己打开并替换网关。
os.environ.setdefault("ASSISTANT_AGENT_ROUTING", "0")
# 第 5 阶段开跑前让文本模型判定每段的生成方式：测试默认关掉，专门测它的用例自己打开并替换网关。
os.environ.setdefault("VIDEO_MODE_JUDGE", "0")
# 分集大纲出来后让文本模型对着概述校对一遍事实：测试默认关掉，专门测它的用例自己打开。
os.environ.setdefault("SCREENWRITING_FACT_CHECK", "0")
