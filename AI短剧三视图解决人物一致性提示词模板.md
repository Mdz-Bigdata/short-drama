# AI短剧：通过三视图解决人物一致性问题

> 📎 **关联文档**：总入口 [README](README.md)。本文件是人物一致性的**提示词模板**权威源；一致性的合成/驱动方法见 [表演细节指南 §10](AI短剧表演细节与提示词指南.md)，跨镜头连续性见 [连续性设计指南](AI短剧连续性设计指南.md)，质检见 [一致性检查清单 §1/§24](<AI 生成短剧一致性检查清单.md>)。

## 1. 核心思路

AI短剧里的人物一致性，主要不是靠“每一镜都重新描述角色”，而是先建立一个稳定的“角色视觉锚点”。三视图就是最常用的角色锚点：正面、侧面、背面。

三视图的作用是把人物的关键视觉信息固定下来，包括：

- 脸型、五官、发型、发色
- 身高、体型、年龄感
- 服装结构、颜色、材质
- 标志性配饰、纹身、伤疤、道具
- 角色气质、身份、时代背景
- 镜头里最容易漂移的细节

后续生成分镜、海报、角色动作、剧情镜头时，都应该引用这张三视图作为角色参考，而不是每次凭文字重新生成。

---

## 2. 推荐工作流

### Step 1：先生成角色三视图

目标：获得一张稳定、清晰、无复杂背景的角色设定图。

要求：

- 同一角色出现在同一画面中
- 包含正面、侧面、背面
- 服装完全一致
- 发型完全一致
- 身材比例一致
- 背景干净，最好是白底或浅灰底
- 不要复杂动作
- 不要戏剧化光影
- 不要多余人物

### Step 2：从三视图提取角色设定词

把生成结果里最稳定的视觉特征整理成“角色锁定描述”。

角色锁定描述应该包括：

- 固定姓名或角色代号
- 年龄与性别
- 脸型与五官
- 发型与发色
- 体型与身高感
- 服装主色与结构
- 标志性细节
- 气质关键词
- 禁止变化项

### Step 3：所有后续镜头都引用三视图

后续提示词结构建议固定为：

```text
角色参考 + 场景 + 动作 + 情绪 + 镜头语言 + 光影 + 风格 + 一致性约束 + 负面提示词
```

### Step 4：每个角色单独建立三视图

如果短剧里有多个主要人物，建议每个角色都单独做一张三视图：

- 主角三视图
- 反派三视图
- 女主三视图
- 配角三视图
- 儿童版、老年版、战损版等特殊状态三视图

---

## 3. 三视图提示词模板

### 3.1 通用三视图模板

```text
A full body character turnaround sheet of [角色名称], showing the same character in three views: front view, side view, and back view, standing in a neutral pose, consistent face, consistent hairstyle, consistent outfit, consistent body proportions.

Character details: [年龄] [性别], [脸型], [五官特征], [发型与发色], [身高体型], wearing [服装描述], with [标志性配饰/道具/疤痕/纹身].

Clean white background, studio lighting, character design sheet, concept art, full body, highly detailed, sharp details, neutral expression, no dramatic pose, no extra characters.

Style: [写实/电影感/国风/赛博朋克/古装/现代都市/悬疑短剧/韩剧感/港风/动漫风]

Negative prompt: different faces, different clothes, inconsistent hairstyle, extra limbs, extra fingers, multiple people, cropped body, blurry, low quality, distorted face, asymmetrical body, random accessories, text, logo, watermark, complex background.
```

### 3.2 中文三视图模板

```text
为 AI 短剧角色 [角色名称] 生成一张完整人物三视图设定图。画面中展示同一个角色的正面、侧面、背面，全身站立，中性姿势，三视图中的脸型、五官、发型、服装、身材比例必须完全一致。

角色设定：[年龄]岁的[性别]，[身份/职业]，[脸型特征]，[眼睛特征]，[鼻子特征]，[嘴唇特征]，[发型与发色]，[身高与体型]。穿着[上衣描述]、[下装描述]、[鞋子描述]，颜色以[主色]和[辅色]为主，材质为[材质]。身上有[标志性配饰/伤疤/纹身/道具]。

视觉风格：[风格关键词]，角色设定图，干净白色背景，均匀棚拍光，全身，高清细节，服装结构清楚，五官清晰，正面侧面背面并排展示。

一致性要求：同一个人物，同一套服装，同一个发型，同一个体型，同一个年龄感，不改变五官，不改变服装颜色，不添加新配饰。

负面提示词：不同脸，不同服装，发型变化，身材变化，多余人物，多余手指，肢体畸形，脸部扭曲，低清晰度，模糊，裁切身体，复杂背景，文字，水印，logo。
```

---

## 4. 角色设定提取模板

生成三视图后，把图像信息整理成下面这份“角色锁定卡”。后续所有镜头都从这里复制角色描述。

```markdown
## 角色锁定卡：[角色名称]

### 基础信息
- 角色名称：
- 性别：
- 年龄感：
- 身份/职业：
- 剧集类型：

### 面部特征
- 脸型：
- 眼睛：
- 眉毛：
- 鼻子：
- 嘴唇：
- 肤色：
- 特殊面部标记：

### 发型
- 发色：
- 发长：
- 发型：
- 刘海/鬓角：
- 是否可变化：不可变化

### 体型
- 身高感：
- 体型：
- 肩宽：
- 姿态：
- 年龄感：

### 服装
- 上衣：
- 下装：
- 外套：
- 鞋子：
- 主色：
- 辅色：
- 材质：
- 服装不可变化项：

### 标志性元素
- 配饰：
- 道具：
- 伤疤/纹身：
- 其他识别点：

### 气质关键词
- 关键词 1：
- 关键词 2：
- 关键词 3：

### 禁止变化
- 不改变脸型
- 不改变发型
- 不改变发色
- 不改变服装颜色
- 不新增配饰
- 不改变年龄感
- 不改变体型
```

---

## 5. AI短剧镜头提示词模板

### 5.1 单镜头通用模板

```text
Use the provided character turnaround sheet as the main reference. Keep the same character identity, same face, same hairstyle, same outfit, same body proportions, and same signature accessories.

Scene: [场景]
Action: [动作]
Emotion: [情绪]
Camera: [镜头语言]
Lighting: [光影]
Style: [短剧风格]

Character: [角色名称], [年龄] [性别], [固定脸型], [固定五官], [固定发型发色], wearing the exact same [固定服装], with [固定标志性元素].

Consistency rules: same person as reference image, identical face, identical hairstyle, identical clothing, identical body shape, no outfit change, no new accessories, no age change.

Negative prompt: different person, different face, different hairstyle, different outfit, changed clothing color, extra accessories, distorted face, bad hands, extra fingers, blurry, low quality, watermark, text, logo.
```

### 5.2 中文单镜头模板

```text
请严格参考上传的角色三视图，生成 AI 短剧镜头。必须保持同一个人物身份、同一张脸、同一个发型、同一套服装、同一个体型和同样的标志性配饰。

角色：[角色名称]，[年龄]岁的[性别]，[身份]，[脸型]，[五官特征]，[发型发色]，穿着与三视图完全一致的[服装描述]，身上保留[标志性配饰/道具/伤疤]。

场景：[具体场景]
动作：[具体动作]
情绪：[情绪状态]
镜头：[近景/中景/全景/特写/低角度/俯拍/推镜/跟拍]
光影：[自然光/冷色夜景/霓虹灯/阴天柔光/电影感逆光]
风格：[现代都市短剧/悬疑短剧/古装短剧/甜宠短剧/复仇爽剧/现实主义]

一致性要求：必须是参考图中的同一个人，脸不能变，发型不能变，发色不能变，服装不能变，体型不能变，年龄感不能变，不要添加新配饰。

负面提示词：换脸，不同人物，发型变化，服装变化，颜色变化，身材变化，年龄变化，多余人物，脸部变形，手部畸形，多余手指，模糊，低质量，文字，水印，logo。
```

---

## 6. 不同短剧类型的三视图示例

### 6.1 现代都市女主

```text
为 AI 短剧女主“林晚”生成一张完整人物三视图设定图。画面中展示同一个角色的正面、侧面、背面，全身站立，中性姿势，三视图中的脸型、五官、发型、服装、身材比例必须完全一致。

角色设定：28岁女性，都市职场律师，鹅蛋脸，清冷明亮的杏眼，细长眉，高鼻梁，自然淡粉色嘴唇，黑色中长直发，发尾微卷，身高约168cm，身材纤细但有力量感。穿着米白色修身西装外套、浅灰色内搭、黑色高腰西裤、黑色尖头高跟鞋，左手佩戴银色细腕表，耳朵佩戴小号珍珠耳钉。

视觉风格：现代都市短剧，写实电影感，角色设定图，干净白色背景，均匀棚拍光，全身，高清细节，服装结构清楚，五官清晰，正面侧面背面并排展示。

一致性要求：同一个人物，同一套服装，同一个发型，同一个体型，同一个年龄感，不改变五官，不改变服装颜色，不添加新配饰。

负面提示词：不同脸，不同服装，发型变化，身材变化，多余人物，多余手指，肢体畸形，脸部扭曲，低清晰度，模糊，裁切身体，复杂背景，文字，水印，logo。
```

### 6.2 复仇爽剧男主

```text
为 AI 短剧男主“陆沉”生成一张完整人物三视图设定图。画面中展示同一个角色的正面、侧面、背面，全身站立，中性姿势，三视图中的脸型、五官、发型、服装、身材比例必须完全一致。

角色设定：32岁男性，隐忍复仇型商业继承人，轮廓分明的长方脸，深邃窄长的眼睛，浓眉，高鼻梁，薄唇，黑色短发向后梳理，身高约185cm，肩宽腿长，体型挺拔。穿着深黑色长款羊毛大衣、黑色高领针织衫、深灰色西裤、黑色皮鞋，右手戴一枚黑曜石戒指，左眉尾有一道很浅的旧伤疤。

视觉风格：复仇爽剧，冷色电影感，角色设定图，干净白色背景，均匀棚拍光，全身，高清细节，服装结构清楚，五官清晰，正面侧面背面并排展示。

一致性要求：同一个人物，同一套服装，同一个发型，同一个体型，同一个年龄感，不改变五官，不改变服装颜色，不添加新配饰。

负面提示词：不同脸，不同服装，发型变化，身材变化，多余人物，多余手指，肢体畸形，脸部扭曲，低清晰度，模糊，裁切身体，复杂背景，文字，水印，logo。
```

### 6.3 古装短剧女主

```text
为 AI 古装短剧女主“沈青梧”生成一张完整人物三视图设定图。画面中展示同一个角色的正面、侧面、背面，全身站立，中性姿势，三视图中的脸型、五官、发型、服装、身材比例必须完全一致。

角色设定：22岁女性，冷静聪慧的侯府庶女，瓜子脸，清澈丹凤眼，细弯眉，小巧高鼻，浅色薄唇，黑色长发盘成半披发古风发髻，发间有一支青玉簪。身高约165cm，身形纤细，气质克制。穿着浅青色交领长裙，外搭白色轻纱披帛，腰间系银白色腰带，裙摆有淡色竹叶暗纹，脚穿白色绣鞋。

视觉风格：古装短剧，东方美学，写实影视感，角色设定图，干净白色背景，均匀棚拍光，全身，高清细节，服装结构清楚，五官清晰，正面侧面背面并排展示。

一致性要求：同一个人物，同一套服装，同一个发型，同一个体型，同一个年龄感，不改变五官，不改变服装颜色，不添加新配饰。

负面提示词：不同脸，不同服装，发型变化，发饰变化，身材变化，多余人物，多余手指，肢体畸形，脸部扭曲，低清晰度，模糊，裁切身体，复杂背景，文字，水印，logo。
```

### 6.4 悬疑短剧反派

```text
为 AI 悬疑短剧反派“周启明”生成一张完整人物三视图设定图。画面中展示同一个角色的正面、侧面、背面，全身站立，中性姿势，三视图中的脸型、五官、发型、服装、身材比例必须完全一致。

角色设定：45岁男性，表面温和的心理医生，偏瘦长脸，眼神平静但压迫感强，眉毛稀疏，高鼻梁，嘴角轻微下垂，黑灰色短发，发际线略高，身高约178cm，体型偏瘦。穿着深棕色羊毛西装外套、米色衬衫、深咖色西裤、棕色皮鞋，佩戴金丝眼镜，右手拿一本黑色皮面笔记本。

视觉风格：悬疑短剧，低饱和写实电影感，角色设定图，干净白色背景，均匀棚拍光，全身，高清细节，服装结构清楚，五官清晰，正面侧面背面并排展示。

一致性要求：同一个人物，同一套服装，同一个发型，同一个体型，同一个年龄感，不改变五官，不改变服装颜色，不添加新配饰。

负面提示词：不同脸，不同服装，发型变化，眼镜消失，身材变化，多余人物，多余手指，肢体畸形，脸部扭曲，低清晰度，模糊，裁切身体，复杂背景，文字，水印，logo。
```

---

## 7. 分镜生成模板

### 7.1 角色进场镜头

```text
严格参考角色三视图，保持同一个人物身份、脸型、五官、发型、服装、体型和标志性配饰完全一致。

角色：[角色名称]，[角色锁定描述]

镜头内容：[角色名称]从[地点]缓慢走入画面，目光看向前方，表情[情绪]。

场景：[地点细节]
镜头语言：中景，轻微推镜，电影感构图，背景轻微虚化
光影：柔和自然光 / 冷色夜景 / 强烈逆光
风格：[短剧类型]

一致性要求：必须与三视图中的人物完全一致，不改变脸，不改变发型，不改变服装，不改变体型。

负面提示词：换脸，换衣服，发型变化，新增配饰，低清晰度，手部畸形，多余人物，文字，水印。
```

### 7.2 情绪特写镜头

```text
严格参考角色三视图，保持同一个人物身份、脸型、五官、发型、服装和标志性细节完全一致。

角色：[角色名称]，[角色锁定描述]

镜头内容：[角色名称]站在[场景]中，表情从[情绪A]逐渐变为[情绪B]，眼神[眼神描述]。

镜头语言：面部特写，浅景深，眼睛清晰，背景虚化
光影：[光影描述]
风格：[短剧类型]

一致性要求：脸部必须与三视图一致，五官比例不变，发型不变，服装领口和配饰保持一致。

负面提示词：不同脸，五官变化，年龄变化，发型变化，服装变化，脸部变形，眼睛畸形，模糊，水印，文字。
```

### 7.3 对话镜头

```text
严格参考角色三视图，保持角色外貌完全一致。

角色A：[角色A名称]，[角色A锁定描述]
角色B：[角色B名称]，[角色B锁定描述]

镜头内容：角色A与角色B在[场景]中对话。角色A表情[情绪]，角色B表情[情绪]。两人保持自然站位。

镜头语言：双人中景，过肩镜头，电影感构图
光影：[光影描述]
风格：[短剧类型]

一致性要求：两个角色都必须分别与各自三视图一致，不混脸，不交换服装，不改变发型，不新增配饰。

负面提示词：角色混淆，换脸，服装交换，发型变化，人物数量错误，多余手指，脸部扭曲，模糊，文字，水印。
```

### 7.4 动作镜头

```text
严格参考角色三视图，保持同一个人物身份、脸型、五官、发型、服装、体型和标志性配饰完全一致。

角色：[角色名称]，[角色锁定描述]

镜头内容：[角色名称]正在[动作]，身体姿态[姿态描述]，表情[情绪]。

场景：[地点]
镜头语言：全身动作镜头，动态构图，轻微运动模糊但脸部清晰
光影：[光影描述]
风格：[短剧类型]

一致性要求：动作可以变化，但人物外貌、发型、服装、身材比例必须与三视图一致。

负面提示词：换脸，换衣服，身材变化，发型变化，肢体畸形，多余手指，脸部模糊，低质量，水印，文字。
```

---

## 8. 不同工具的使用建议

### 8.1 Midjourney

建议用法：

```text
[上传三视图图片链接] cinematic shot of the same character, [场景], [动作], [情绪], same face, same hairstyle, same outfit, same body proportions, consistent character identity, realistic short drama style --cref [角色参考图链接] --cw 80 --ar 9:16 --style raw
```

参数建议：

- `--cref`：角色参考
- `--cw 70-100`：角色一致性权重
- `--ar 9:16`：短剧竖屏比例
- `--style raw`：减少风格漂移
- `--s 50-150`：降低过度风格化

### 8.2 Stable Diffusion / SDXL

建议要点：

- 三视图用于训练 LoRA 或作为 IP-Adapter 参考
- 使用 ControlNet OpenPose 控制动作
- 使用 Reference Only / IP-Adapter FaceID 控制脸
- 使用固定 seed 测试一致性

通用提示词：

```text
same character as reference image, consistent face, consistent hairstyle, consistent outfit, full body, cinematic vertical short drama frame, [scene], [action], [emotion], realistic lighting, high detail
```

负面提示词：

```text
different face, inconsistent character, different clothes, changed hairstyle, extra fingers, bad hands, distorted face, blurry, low quality, watermark, text, logo
```

### 8.3 即梦 / 可灵 / Runway / Pika

建议用法：

1. 先上传三视图作为角色参考图
2. 在提示词第一句强调“严格参考角色三视图”
3. 每个镜头都重复角色锁定描述
4. 不要只写“同一个人”，要写清楚哪些不能变
5. 镜头动作可以变，角色外观不要变

视频提示词结构：

```text
严格参考上传的角色三视图，保持同一个人物、同一张脸、同一个发型、同一套服装、同一个体型。[角色名称]在[场景]中[动作]，表情[情绪]。镜头为[镜头语言]，光影为[光影风格]，整体风格为[短剧类型]。人物外观不能变化，服装不能变化，发型不能变化，不要新增配饰。
```

---

## 9. 人物一致性强化词库

### 9.1 正向一致性词

```text
same character, same person, consistent identity, identical face, consistent facial features, same hairstyle, same hair color, same outfit, identical clothing, same body proportions, same age appearance, same signature accessories, character reference sheet, character turnaround, front side back view
```

中文：

```text
同一个人物，同一张脸，同一套服装，同一个发型，同一个发色，同一个体型，同一个年龄感，同样的标志性配饰，严格参考角色三视图，保持人物身份一致，保持五官一致，保持服装结构一致
```

### 9.2 负面约束词

```text
different person, different face, face changed, inconsistent identity, different hairstyle, changed hair color, different outfit, clothing changed, body shape changed, age changed, random accessories, extra character, duplicate character, distorted face, bad anatomy, bad hands, extra fingers, missing fingers, blurry, low quality, text, logo, watermark
```

中文：

```text
不同人物，换脸，五官变化，发型变化，发色变化，服装变化，衣服颜色变化，体型变化，年龄变化，随机配饰，多余人物，重复人物，脸部变形，手部畸形，多余手指，缺失手指，模糊，低质量，文字，logo，水印
```

---

## 10. 常见问题与解决办法

### 问题 1：脸一致，但衣服变了

解决：在提示词里把服装拆细。

不要只写：

```text
wearing a black suit
```

建议写：

```text
wearing the exact same black wool long coat, black turtleneck sweater, dark gray trousers, black leather shoes, no clothing change, no color change
```

### 问题 2：衣服一致，但脸变了

解决：强化脸部锁定。

```text
identical face as reference, same oval face shape, same almond eyes, same high nose bridge, same thin lips, same facial proportions, no face change
```

### 问题 3：发型经常漂移

解决：把发型写成不可变化项。

```text
same black shoulder-length straight hair with slightly curled ends, no hairstyle change, no bangs change, no hair color change
```

### 问题 4：不同镜头年龄感变化

解决：固定年龄感和皮肤状态。

```text
same 28-year-old appearance, mature but youthful face, smooth skin, no aging, no younger version, no older version
```

### 问题 5：多人镜头角色混淆

解决：分开描述角色，并写清楚禁止混脸。

```text
Character A and Character B must remain visually distinct, do not swap faces, do not swap outfits, each character must match their own reference sheet
```

---

## 11. 最终可复制总模板

```text
严格参考上传的角色三视图，生成 AI 短剧竖屏镜头。必须保持同一个人物身份、同一张脸、同一个发型、同一个发色、同一套服装、同一个体型、同一个年龄感和同样的标志性配饰。

角色：[角色名称]，[年龄]岁的[性别]，[身份/职业]。[脸型]，[眼睛]，[眉毛]，[鼻子]，[嘴唇]，[肤色]。[发型与发色]，[身高体型]。穿着与三视图完全一致的[上衣]、[下装]、[外套]、[鞋子]，颜色为[主色]和[辅色]，材质为[材质]。保留[标志性配饰/伤疤/纹身/道具]。

场景：[具体场景]
动作：[具体动作]
情绪：[情绪状态]
镜头语言：[近景/中景/全景/特写/低角度/俯拍/推镜/跟拍]
光影：[自然光/冷色夜景/霓虹灯/阴天柔光/电影感逆光]
画幅：9:16 竖屏短剧画幅
风格：[现代都市短剧/悬疑短剧/古装短剧/甜宠短剧/复仇爽剧/现实主义]

一致性要求：必须是参考三视图中的同一个人物。脸不能变，五官不能变，发型不能变，发色不能变，服装不能变，服装颜色不能变，体型不能变，年龄感不能变，标志性配饰不能变，不要添加新配饰，不要生成其他人物。

负面提示词：不同人物，换脸，五官变化，发型变化，发色变化，服装变化，服装颜色变化，体型变化，年龄变化，随机配饰，多余人物，重复人物，角色混淆，脸部变形，眼睛畸形，手部畸形，多余手指，缺失手指，肢体畸形，模糊，低质量，复杂背景，文字，logo，水印。
```

---

## 12. 实操建议

- 三视图阶段不要追求剧情感，先追求“清楚、稳定、完整”。
- 角色三视图最好是全身白底，不要电影场景图。
- 每个主角都单独做三视图，不要把多个角色塞在一张设定图里。
- 后续每个镜头都复制“角色锁定描述”，不要只写角色名。
- 镜头提示词里，动作和情绪可以变化，脸、发型、服装、体型不要变化。
- 如果工具支持参考图权重，优先提高角色参考权重，降低风格化权重。
- 如果要做系列短剧，建议建立一个“角色圣经”文档，所有分镜都从里面复制设定。

---

## 13. 简版工作流

```text
1. 生成角色三视图
2. 从三视图提取角色锁定卡
3. 后续每个镜头引用三视图
4. 每条提示词重复角色锁定描述
5. 明确写出禁止变化项
6. 多人镜头分别引用各自三视图
7. 发现漂移后，补充更具体的负面提示词
```
