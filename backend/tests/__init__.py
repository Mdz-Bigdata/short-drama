"""Backend tests for the production pipeline."""

import os

# 高清身份视图会在设定集通过后再发两次出图请求；测试里的网关多数没被替身替换，
# 默认关掉，免得测试去连真实供应商。专门测它的用例自己把开关打开。
os.environ.setdefault("CHARACTER_HD_VIEWS", "0")
os.environ.setdefault("CHARACTER_DETAIL_FILL", "0")
