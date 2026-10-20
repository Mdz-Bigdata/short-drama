# 文物数字展厅来源说明

本模块原始项目为 **zybkpro-museum · 文物数字展厅**，原项目标语为“穿越千年，触摸文明的温度”。

- 原始在线体验：https://www.zybkpro.top/threejs/museum/
- 原始代码包：用户提供的 `zybkpro-museum.zip`
- 原始 package 声明：代码采用 MIT License
- 原始技术栈：React、Vite、Three.js、React Three Fiber、Drei

集成时保留了 8 件文物的完整中文展签、故事、24 条问答、细节说明、模型来源、模型变换，以及原项目 logo、缩略图和 GLB。每件模型在界面中继续展示其独立的 `sourceLabel` 和 `sourceUrl`。

独立 Vite 入口、构建配置和依赖清单没有复制，因为本模块已原生接入 short-drama 的 React 19 前端构建体系。Three.js Draco 解码文件随主应用静态托管，不访问 Google CDN。
