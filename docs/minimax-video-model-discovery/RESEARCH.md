# minimax 视频模型发现修复研究

## 问题

模型配置中心在视频分类选择 MiniMax 后调用通用 `/models`。该接口返回 `MiniMax-M2.*` 文本模型，而旧分类回退逻辑又把无模态元数据的返回项全部改标为视频，造成截图中的错误列表。

## 官方能力

MiniMax 视频生成接口目录包含：

- `MiniMax-H3`（依据用户提供的 H3 v2 接口合同）
- `MiniMax-Hailuo-2.3`
- `MiniMax-Hailuo-2.3-Fast`
- `MiniMax-Hailuo-02`

H3 创建接口为 `POST /v2/video_generation`，使用多模态 `content[]`；Hailuo 公开接口使用 `/v1/video_generation`。官方文档没有声明通用 `/models` 会返回完整视频模型目录，因此不能把它的文本模型响应当成视频目录。

## 决策

1. 模型配置供应商 ID 与显示名称统一为 `minimax`。
2. 通用模型接口只用于无费用的鉴权/连通性验证；其 MiniMax 文本模型响应不进入视频下拉框。
3. 鉴权通过后返回经过代码版本和测试锁定的视频模型目录，其中包括 H3 和 Hailuo。
4. 其他供应商仍使用动态发现，不扩大本次改动范围。
5. API Key 仅随单次 HTTPS 请求进入服务端内存；不写入日志、文档、源码或前端响应。

## 参考

- https://platform.minimaxi.com/docs/api-reference/api-overview
- https://platform.minimax.io/docs/api-reference/video-generation-i2v
- https://platform.minimax.io/docs/release-notes/apis
