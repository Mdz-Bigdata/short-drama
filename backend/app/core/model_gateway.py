# -*- coding: utf-8 -*-
import logging
import os
import random
import re
from typing import Dict

from app.platform.runtime_models import runtime_model_registry
from app.platform.runtime_skills import runtime_skill_registry

logger = logging.getLogger("app.core.model_gateway")

class ModelGateway:
    """
    多模型网关 (Model Gateway)
    提供文本/多模态、文生图、视频生成、配音的对外接口，并内置离线高保真智能生成引擎
    """
    
    # 8种站位法
    BLOCKING_STANDS = [
        "核心镜头站位 (主角居中心，配角四周对称平衡)",
        "对话切换站位 (正反打OTS过肩站位)",
        "三角关系站位 (主角居中景，配角居前景与背景形成三角形)",
        "空间象征站位 (利用物理高度差仰俯拍表现权力阶级)",
        "运动固定站位 (角色沿中轴线同向移动，追踪镜头)",
        "对称仪式站位 (沿画面中轴线完美对称排列)",
        "冲突对峙站位 (两方对立左右，留白大面积张力空间)",
        "前后中景层次站位 (前景虚化，中景主角，背景环境)"
    ]
    
    # 16种环境构图
    COMPOSITIONS = [
        "长廊尽头镜头 (纵深线条制造压迫感)",
        "空旷广场镜头 (角色在大空间极度缩小展现孤立)",
        "窗边停顿镜头 (窗框为界，思考与思念场景)",
        "桥面远景镜头 (延伸空间体现分别或离开宿命感)",
        "街口等待镜头 (都市复杂十字街头等待霓虹闪烁)",
        "过道跟拍镜头 (狭长跟拍，急迫行走与临场感)",
        "楼顶俯视镜头 (俯瞰繁华城市夜景表现虚无与孤单)",
        "电梯开门镜头 (电梯开关动作制造揭示与出场感)",
        "室内角落镜头 (角色置于狭窄边角展现被困局促感)",
        "门口压迫镜头 (用门框封锁角色形成对峙张力)",
        "巷道纵深镜头 (狭窄通道暗示跟踪或跟踪追捕)",
        "雾中小路镜头 (低能见度营造梦幻或朦胧宿命)",
        "雨巷倒影镜头 (地面大量积水反光折射霓虹增加层次)",
        "森林穿行镜头 (树木斑驳光影及遮挡营造探索)",
        "地下通道镜头 (封闭昏暗地下走廊营造黑暗追逐)",
        "海边留白镜头 (海面天空大面积空白人物极小，诗意收尾)"
    ]
    
    # 36种运镜系统
    CAMERA_MOVEMENTS = [
        "Slow Dolly In (慢推近景)", "Slow Dolly Out (慢拉远)", "Crane Up (低升俯视)", 
        "Steadicam Side Follow (贴身跟移)", "360-degree Orbit (环绕凝视)", "Dutch Angle & Spin (斜角旋转)",
        "Rear Chase Shot (背后追拍)", "Frontal Tracking Retreat (正面退拍)", "Lateral Tracking (侧面平行跟拍)", 
        "Over-the-shoulder Chase (过肩跟拍)", "POV Traverse (第一人称穿行)", "Handheld Shake (手持晃动)",
        "Zoom / Snap Push (快速突进)", "Zolly / Fast Pull Back (冲击拉远)", "Drone Dive (俯冲下降)", 
        "Low-angle Push (低机位仰拍推进)", "High-angle Follow (高机位压迫跟拍)", "Extreme Close-up Dolly (极近特写推进)",
        "Pan Reveal (慢摇揭示)", "Whip Pan (甩镜转场)", "Foreground Occlusion (前景遮挡转场)", 
        "Empty Track Transition (空镜推轨转场)", "Match Cut (匹配转场)", "Out-of-focus Bokeh (变焦散景转场)",
        "Rack Focus (焦点转移)", "Macro Sweeping (微距扫过)", "Depth of Field Drift (景深漂移)", 
        "Detail Tracking (细节追踪)", "Light Sweep (光影扫描)", "Reverse Rack Focus (反向焦点折返)",
        "Establishing Shot (远景建立)", "Static Stare (静止凝视)", "Floating (漂浮移动)", 
        "Bullet Time Dolly (时间凝固推进)", "Enclosing Push (环境压迫推进)", "Dolly Zoom (希区柯克变焦)"
    ]

    # 22种题材的短链与特征字典映射，保证服务层短链与题材属性装填完全兼容
    GENRE_TEMPLATES = {
        "romance": {"short_link": "romance_contract_love", "genre_desc": "豪门言情甜宠剧，适合微信视频号/抖音快手"},
        "rebirth_revenge": {"short_link": "rebirth_queen_revenge", "genre_desc": "重生打脸复仇剧"},
        "campus": {"short_link": "campus_secret_love", "genre_desc": "青春校园暗恋剧"},
        "family": {"short_link": "family_mother_awake", "genre_desc": "都市家庭主妇觉醒剧"},
        "retro_romance": {"short_link": "retro_army_love", "genre_desc": "年代怀旧情感剧"},
        "male_counterattack": {"short_link": "male_dragon_king", "genre_desc": "男频赘婿战神归来逆袭剧"},
        "mystery": {"short_link": "mystery_abyss_stare", "genre_desc": "悬疑推理犯罪剧"},
        "time_travel": {"short_link": "time_travel_sign", "genre_desc": "穿越架空系统流爽剧"},
        "palace_intrigue": {"short_link": "palace_queen_revenge", "genre_desc": "古装宫斗权谋剧"},
        "xianxia": {"short_link": "xianxia_demon_rise", "genre_desc": "仙侠修真热血短剧"},
        "urban_realism": {"short_link": "urban_lawyer_win", "genre_desc": "都市商战律政悬疑剧"},
        "sci_fi": {"short_link": "scifi_cyborg_awake", "genre_desc": "赛博朋克科幻爽剧"},
        "horror": {"short_link": "horror_paper_coffin", "genre_desc": "民俗灵异恐怖剧"},
        "military": {"short_link": "military_lone_wolf", "genre_desc": "特种兵硬汉反恐短剧"},
        "sports": {"short_link": "sports_iron_punch", "genre_desc": "格斗竞技热血爽剧"},
        "food": {"short_link": "food_healing_face", "genre_desc": "都市治愈美食生活剧"},
        "overseas_us": {"short_link": "overseas_wolf_love", "genre_desc": "出海欧美狼人爱情剧"},
        "overseas_other": {"short_link": "overseas_east_love", "genre_desc": "出海中东异域爱情剧"},
        "interactive": {"short_link": "interactive_choice", "genre_desc": "互动多结局创新短剧"},
        "comedy": {"short_link": "comedy_funny_boy", "genre_desc": "反转沙雕爆笑喜剧"},
        "car": {"short_link": "car_ark_accessory", "genre_desc": "科技车载方舟极客剧"},
        "general": {"short_link": "general_revenge_king", "genre_desc": "都市情感逆袭短剧"}
    }

    def __init__(self):
        # 1. 尝试载入项目根目录或当前目录下的 .env 配置文件
        try:
            from dotenv import load_dotenv
            import os
            # 优先加载当前工作目录下的 .env
            load_dotenv()
            # 然后尝试向上寻找，加载项目根目录下的 .env
            gateway_dir = os.path.dirname(os.path.abspath(__file__))
            root_dotenv = os.path.abspath(os.path.join(gateway_dir, "..", "..", "..", ".env"))
            if os.path.exists(root_dotenv):
                load_dotenv(root_dotenv)
                logger.info(f"[ModelGateway] 成功从根目录载入 .env 配置文件: {root_dotenv}")
        except ImportError:
            pass

        # 2. 从环境变量读取（包括 .env 载入的）
        env_deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        env_deepseek_url = os.getenv("DEEPSEEK_BASE_URL")
        env_deepseek_model = os.getenv("DEEPSEEK_MODEL_NAME")

        env_seedance_key = os.getenv("SEEDANCE_API_KEY")
        env_seedance_url = os.getenv("SEEDANCE_BASE_URL")
        env_seedance_model = os.getenv("SEEDANCE_MODEL_NAME")

        env_qwen_key = os.getenv("QWEN_API_KEY")
        env_qwen_url = os.getenv("QWEN_BASE_URL")
        env_qwen_model = os.getenv("QWEN_MODEL_NAME")

        env_gemini_key = os.getenv("GEMINI_API_KEY")
        env_gemini_url = os.getenv("GEMINI_BASE_URL")
        env_gemini_model = os.getenv("GEMINI_MODEL_NAME")

        env_agnes_key = os.getenv("AGNES_API_KEY")
        env_agnes_url = os.getenv("AGNES_BASE_URL")
        env_agnes_model = os.getenv("AGNES_MODEL_NAME")

        # 3. 加载 config.json 文件作为补充/兜底
        json_config = {}
        import json
        config_paths = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config.json"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"),
            "config.json"
        ]
        for path in config_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        json_config = json.load(f)
                        logger.info(f"[ModelGateway] 成功从 {path} 载入模型补充配置")
                        break
                except Exception as e:
                    logger.error(f"[ModelGateway] 读取配置文件 {path} 失败: {str(e)}")

        # 4. 非敏感配置可由 config.json 补充；所有 API key 只允许来自服务端环境变量。
        def get_valid_value(env_val, json_section, json_key, default_val):
            # 判断环境变量是否有效（非空且非占位符）
            if env_val and isinstance(env_val, str) and not env_val.startswith("YOUR_") and env_val.strip():
                return env_val
            # 否则尝试从 json 文件中获取
            if json_config and json_section in json_config:
                json_val = json_config[json_section].get(json_key)
                if json_val and isinstance(json_val, str) and not json_val.startswith("YOUR_") and json_val.strip():
                    return json_val
            return default_val

        def get_secret(env_val, placeholder):
            if env_val and isinstance(env_val, str) and not env_val.startswith("YOUR_") and env_val.strip():
                return env_val
            return placeholder

        self.deepseek_key = get_secret(env_deepseek_key, "YOUR_DEEPSEEK_API_KEY")
        self.deepseek_base_url = get_valid_value(env_deepseek_url, "deepseek", "base_url", env_deepseek_url or "https://api.deepseek.com/v1")
        self.deepseek_model_name = get_valid_value(env_deepseek_model, "deepseek", "model_name", env_deepseek_model or "deepseek-chat")

        self.seedance_key = get_secret(env_seedance_key, "YOUR_SEEDANCE_API_KEY")
        self.seedance_base_url = get_valid_value(env_seedance_url, "seedance", "base_url", env_seedance_url or "https://api.seedance.ai/v1")
        self.seedance_model_name = get_valid_value(env_seedance_model, "seedance", "model_name", env_seedance_model or "seedance-llm")
        # Seedream 文生图模型 + 尺寸 (与 Seedance 图生视频同属火山 Ark，统一风格)
        self.seedance_image_model = os.getenv("SEEDANCE_IMAGE_MODEL_NAME") or "doubao-seedream-4-5-251128"
        # Seedream 4.5 要求图片 ≥3686400 像素；1440x2560 为 9:16 竖屏且达标
        self.seedance_image_size = os.getenv("SEEDANCE_IMAGE_SIZE") or "1440x2560"
        # Seedream 文生图 AI 水印/标记：必须开启！火山 Ark 图生视频审核靠该 AI 标记识别"自家 AI 图"，
        # 关闭后写实人脸首帧会被判「疑似真人 InputImageSensitiveContentDetected」而拒。默认 True，
        # 同时也满足"AI 生成内容须显著标识"的合规要求。可用 SEEDANCE_IMAGE_WATERMARK=0 关闭(不建议)。
        self.seedance_image_watermark = (os.getenv("SEEDANCE_IMAGE_WATERMARK", "1").strip() not in ("0", "false", "False", ""))
        # 火山 Ark 专用代理 (当部署环境无法直连 ark.cn-beijing.volces.com 时，
        # 设置 ARK_PROXY=http://host:port 即可让所有 Ark 请求走该代理)
        self.ark_proxy = os.getenv("ARK_PROXY") or os.getenv("SEEDANCE_PROXY") or ""
        # 火山「可信素材库」已授权真人素材白名单：演员在控制台/即梦App完成一次性真人认证入库后，
        # 把授权素材的 volces.com 直链填到 .env 的 ARK_AUTHORIZED_FACE_ASSETS (逗号分隔) 或
        # config.json 的 seedance.authorized_face_assets。这些已授权真人素材作为首帧/参考图时，
        # Ark 图生视频不会再判「疑似真人 InputImageSensitiveContentDetected」而拒。
        _auth_faces = os.getenv("ARK_AUTHORIZED_FACE_ASSETS") or ""
        if not _auth_faces and isinstance(json_config.get("seedance"), dict):
            _auth_faces = json_config["seedance"].get("authorized_face_assets") or ""
        if isinstance(_auth_faces, (list, tuple)):
            self.ark_authorized_faces = [str(u).strip() for u in _auth_faces if u and str(u).strip()]
        else:
            self.ark_authorized_faces = [u.strip() for u in str(_auth_faces).split(",") if u.strip()]

        # 「角色 -> 已授权真人素材」映射：指定某角色固定用某位授权演员的脸做该角色镜头的首帧。
        # 键支持角色位(主角/反派 或 protagonist/antagonist)与具体角色名(若已知)。
        # 来源：.env 的 ARK_AUTHORIZED_FACE_MAP="主角=https://...volces.com/a.png;反派=https://...volces.com/b.png"
        #      (多项用英文分号 ; 分隔，键值用 = 分隔，避免与 URL 里的逗号冲突)
        # 或 config.json 的 seedance.authorized_face_map = {"主角": "url", "反派": "url"}
        _face_map = {}
        if isinstance(json_config.get("seedance"), dict):
            _jm = json_config["seedance"].get("authorized_face_map")
            if isinstance(_jm, dict):
                _face_map = {str(k).strip(): str(v).strip() for k, v in _jm.items() if k and v and str(v).strip()}
        _raw_map = os.getenv("ARK_AUTHORIZED_FACE_MAP") or ""
        if isinstance(_raw_map, str) and _raw_map.strip():
            for item in _raw_map.split(";"):
                if "=" in item:
                    k, v = item.split("=", 1)
                    if k.strip() and v.strip():
                        _face_map[k.strip()] = v.strip()
        self.ark_authorized_face_map = _face_map
        # 映射值并入授权白名单，确保合规护栏放行这些素材上传 Ark
        self.ark_authorized_faces = list(dict.fromkeys(self.ark_authorized_faces + list(_face_map.values())))
        # Seedance 2.0 多模态文本模型 (用于提示词工程化优化 / 多模态理解)；
        # 未显式配置则留空，优化器跳过 Ark 文本模型，直接用 deepseek/agnes，避免欠费/未开通时的无效调用
        self.seedance_text_model = (os.getenv("SEEDANCE_TEXT_NAME") or "").strip()
        # 是否启用 Seedance 2.0 提示词优化器 (sd2-pe)
        self.seedance_prompt_opt = (os.getenv("SEEDANCE_PROMPT_OPT", "1").strip() not in ("0", "false", "False", ""))
        self._sd2_opt_prompt_cache = None

        self.qwen_key = get_secret(env_qwen_key, "YOUR_QWEN_API_KEY")
        self.qwen_base_url = get_valid_value(env_qwen_url, "qwen", "base_url", env_qwen_url or "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.qwen_model_name = get_valid_value(env_qwen_model, "qwen", "model_name", env_qwen_model or "qwen-turbo")

        self.gemini_key = get_secret(env_gemini_key, "YOUR_GEMINI_API_KEY")
        self.gemini_base_url = get_valid_value(env_gemini_url, "gemini", "base_url", env_gemini_url or "https://generativelanguage.googleapis.com")
        self.gemini_model_name = get_valid_value(env_gemini_model, "gemini", "model_name", env_gemini_model or "gemini-3.1-pro-image")

        self.agnes_key = get_secret(env_agnes_key, "YOUR_AGNES_API_KEY")
        self.agnes_base_url = get_valid_value(env_agnes_url, "agnes", "base_url", env_agnes_url or "https://apihub.agnes-ai.com/v1")
        self.agnes_model_name = get_valid_value(env_agnes_model, "agnes", "model_name", env_agnes_model or "agnes-2.0-flash")
        # Agnes 网关的文生图与图生视频模型 ID (经实测可用，可用环境变量覆盖)
        self.agnes_image_model = os.getenv("AGNES_IMAGE_MODEL_NAME") or "agnes-image-2.1-flash"
        self.agnes_video_model = os.getenv("AGNES_VIDEO_MODEL_NAME") or "agnes-video-v2.0"
        # 按 host 维度记录"物理不可达"的厂商域名 (如部署在海外时中国 Ark/DeepSeek 端点 SSL 中断)。
        # 关键：绝不能用一个全局布尔把所有 provider 一起熔断 —— 否则一个不可达的端点(Ark)失败后，
        # 会把另一个可达的端点(Agnes)也短路成离线，导致整条流水线只能出占位图/占位视频。
        # host -> 熔断到期时间戳 (time.time())。带冷却的时间型熔断 + 半开恢复：
        # 到期后自动半开(允许一次试探调用)，成功即彻底恢复，失败则按失败次数延长冷却。
        # 关键修复：旧实现是永久 set，一旦某 host 入集合就永不再试 → _note_host_ok 永无机会清除 →
        # 本机唯一可达的 Agnes 一旦因瞬时抖动被误熔断，文本/图/视频全部永久短路、整条线瘫痪。
        self._broken_hosts = {}
        # host -> 连续 SSL 失败次数。失败越多冷却越久(死端点如 Ark 少重试)，任一次成功即清零。
        self._host_fail = {}
        self._broken_threshold = 2
        self._broken_cooldown = 45      # 基础冷却秒数 (半开重试间隔，按失败次数线性放大)
        self._broken_cooldown_max = 600  # 冷却上限秒数
        # TLS certificate verification is mandatory. A custom CA bundle may be
        # supplied for enterprise proxies; certificate verification cannot be bypassed.
        self.tls_verify = os.getenv("PROVIDER_CA_BUNDLE") or True

    @staticmethod
    def _host_of(base_url: str) -> str:
        """从 base_url 中解析出主机名，作为熔断粒度的键。"""
        try:
            from urllib.parse import urlparse
            return (urlparse(base_url).netloc or base_url).lower()
        except Exception:
            return (base_url or "").lower()

    def _is_host_broken(self, base_url: str) -> bool:
        """是否处于熔断短路中。带半开恢复：冷却到期则解除熔断、放行一次试探调用
        (保留失败计数；若试探再失败会按更长冷却重新熔断)。"""
        import time
        host = self._host_of(base_url)
        expiry = self._broken_hosts.get(host)
        if not expiry:
            return False
        if time.time() >= expiry:
            # 冷却到期：进入半开，移除熔断标记放行一次试探 (失败计数不清零，留给试探后决定)
            self._broken_hosts.pop(host, None)
            logger.info(f"[ModelGateway] {host} 冷却到期，半开放行一次试探调用。")
            return False
        return True

    def _note_host_ok(self, base_url: str):
        """该域名一次调用成功：清零失败计数并彻底撤销熔断 (端点已恢复可达)。"""
        host = self._host_of(base_url)
        if host:
            self._host_fail[host] = 0
            self._broken_hosts.pop(host, None)

    def _mark_host_broken(self, base_url: str):
        """记录一次 SSL 不可达；连续失败达阈值即熔断一段冷却时间 (失败越多冷却越久，死端点少重试)。"""
        import time
        host = self._host_of(base_url)
        if not host:
            return
        self._host_fail[host] = self._host_fail.get(host, 0) + 1
        n = self._host_fail[host]
        if n >= self._broken_threshold:
            cooldown = min(self._broken_cooldown * (n - self._broken_threshold + 1), self._broken_cooldown_max)
            self._broken_hosts[host] = time.time() + cooldown
            logger.info(f"[ModelGateway] {host} 连续 {n} 次 SSL 不可达，熔断短路 {cooldown:.0f}s (到期自动半开重试，其它厂商不受影响)。")

    def _proxies_for(self, base_url: str):
        """代理选择：
        - 若显式配置了代理 (SEEDANCE_PROXY / HTTPS_PROXY / ALL_PROXY)，所有上游调用走该代理。
          这是本机到火山 Ark / DeepSeek 被网络环境定向 TLS 阻断 (SSLEOFError) 时跑通的唯一可靠途径。
          例: 在 backend/.env 加 SEEDANCE_PROXY=http://127.0.0.1:7890 (指向本机科学上网客户端的 HTTP 代理端口)。
        - 未配置时返回空代理字典，直连并忽略可能损坏的系统代理。"""
        proxy = (os.getenv("SEEDANCE_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
                 or os.getenv("ALL_PROXY") or os.getenv("all_proxy") or "").strip()
        if proxy:
            return {"http": proxy, "https": proxy}
        return {"http": None, "https": None}

    # ==================================================================================
    # 真实模型接入：provider 凭证解析 + 多 provider 降级链 + 底层 HTTP 调用
    # ==================================================================================
    @staticmethod
    def _is_valid_key(k) -> bool:
        """判断一个 API Key 是否有效 (非空、非占位符)"""
        return bool(k and isinstance(k, str) and not k.startswith("YOUR_") and k.strip())

    @staticmethod
    def _is_ark_native(url: str) -> bool:
        """是否为火山 Ark 生态自产素材 (Seedream 文生图产物 / 可信素材库授权素材，域名含 volces.com)。
        Ark 图生视频内容审核只信任火山自产或已授权素材；外部写实图(Agnes 等)会被判「疑似真人」拒绝。"""
        return bool(url and isinstance(url, str) and ".volces.com" in url)

    def _ark_safe_image(self, url: str) -> bool:
        """该图能否安全作为首帧/参考图上传给 Ark 视频：火山自产，或在已授权真人素材白名单内。"""
        return self._is_ark_native(url) or (bool(url) and url in self.ark_authorized_faces)

    def resolve_authorized_face(self, name: str = None, role: str = None) -> str:
        """解析某角色对应的已授权真人素材 URL：先按具体角色名精确匹配，再按角色位(主角/反派)匹配。
        未配置则返回 None (该角色走常规文生图/文生视频流程)。"""
        m = getattr(self, "ark_authorized_face_map", None) or {}
        if not m:
            return None
        if name and name in m:
            return m[name]
        if role and role in m:
            return m[role]
        alias = {"主角": "protagonist", "反派": "antagonist"}.get(role)
        if alias and alias in m:
            return m[alias]
        return None

    def _provider_creds(self, name: str):
        """根据 provider 名返回 (api_key, base_url, 默认文本模型ID)"""
        table = {
            "qwen": (self.qwen_key, self.qwen_base_url, self.qwen_model_name),
            "seedance": (self.seedance_key, self.seedance_base_url, self.seedance_model_name),
            "gemini": (self.gemini_key, self.gemini_base_url, self.gemini_model_name),
            "agnes": (self.agnes_key, self.agnes_base_url, self.agnes_model_name),
            "deepseek": (self.deepseek_key, self.deepseek_base_url, self.deepseek_model_name),
        }
        return table.get(name, table["deepseek"])

    @staticmethod
    def _detect_provider(model: str, default: str = "deepseek") -> str:
        """从前端传入的模型名推断目标 provider"""
        m = (model or "").lower()
        if "qwen" in m:
            return "qwen"
        if "doubao" in m or "seedance" in m:
            return "seedance"
        if "gemini" in m:
            return "gemini"
        if "agnes" in m:
            return "agnes"
        if "deepseek" in m:
            return "deepseek"
        return default

    def _http_chat(self, api_key: str, base_url: str, api_model: str, system_prompt: str, user_content: str, timeout: int = 180):
        """底层 OpenAI 兼容 /chat/completions 调用，成功返回文本，失败返回 None"""
        if self._is_host_broken(base_url):
            return None
        try:
            import requests
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": api_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.7,
                # 约束最大输出，避免模型(如 deepseek-v4-pro)在超长剧本上失控生成、
                # 连接被字节间慢吐拖垮 (曾观测到单次调用挂起 15 分钟后 "Response ended prematurely")。
                "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "8000")),
            }
            url = base_url.rstrip('/') + "/chat/completions"
            # 部分端点(如本网络位置的火山 Ark / DeepSeek)会在 TLS 握手阶段被定向 RST(SSL UNEXPECTED_EOF)。
            # 对瞬时网络错误退避重试一次即认输并熔断，随后由熔断器静默跳过该域名、无缝降级到可达 provider，
            # 避免"反复重试 + 逐行刷屏"。日志降为 debug，被阻断主机不再污染 INFO 级日志。
            import time
            attempts = 2
            for attempt in range(attempts):
                try:
                    r = requests.post(url, json=payload, headers=headers, timeout=timeout, proxies=self._proxies_for(base_url), verify=self.tls_verify)
                    if r.status_code == 200:
                        self._note_host_ok(base_url)
                        return r.json()["choices"][0]["message"]["content"]
                    logger.error(f"[ModelGateway] chat({api_model}) 响应错误 {r.status_code}: {r.text[:200]}")
                    return None
                except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError) as e:
                    if attempt < attempts - 1:
                        logger.debug(f"[ModelGateway] chat({api_model}) 瞬时网络抖动第{attempt+1}次重试: {str(e)[:90]}")
                        time.sleep(min(2 * (attempt + 1), 4))
                        continue
                    raise
        except Exception as e:
            logger.debug(f"[ModelGateway] chat({api_model}) 不可达(重试耗尽，将自动降级): {str(e)[:160]}")
            self._mark_host_broken(base_url)
        return None

    def _http_image(self, api_key: str, base_url: str, api_model: str, prompt: str, extra: dict = None, timeout: int = 180):
        """底层 OpenAI 兼容 /images/generations 调用，成功返回图片 URL，失败返回 None。
        extra 用于注入不同厂商所需的额外字段 (如火山 Ark Seedream 的 response_format/size/watermark)。"""
        if self._is_host_broken(base_url):
            return None
        try:
            import requests
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": api_model, "prompt": prompt}
            if extra:
                payload.update(extra)
            url = base_url.rstrip('/') + "/images/generations"
            import time
            attempts = 2
            for attempt in range(attempts):
                try:
                    r = requests.post(url, json=payload, headers=headers, timeout=timeout, proxies=self._proxies_for(base_url), verify=self.tls_verify)
                    if r.status_code == 200:
                        data = r.json().get("data", [{}])
                        if data:
                            u = data[0].get("url") or data[0].get("b64_json")
                            if u and isinstance(u, str) and u.startswith("http"):
                                self._note_host_ok(base_url)
                                return u
                    logger.error(f"[ModelGateway] image({api_model}) 响应错误 {r.status_code}: {r.text[:200]}")
                    return None
                except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError) as e:
                    # 瞬时 TLS/连接抖动：退避重试一次即认输并熔断，随后静默降级到可达 provider
                    if attempt < attempts - 1:
                        logger.debug(f"[ModelGateway] image({api_model}) 瞬时网络抖动第{attempt+1}次重试: {str(e)[:90]}")
                        time.sleep(min(2 * (attempt + 1), 4))
                        continue
                    raise
        except Exception as e:
            logger.debug(f"[ModelGateway] image({api_model}) 不可达(重试耗尽，将自动降级): {str(e)[:160]}")
            self._mark_host_broken(base_url)
        return None

    @staticmethod
    def _extract_mp4(d) -> str:
        """从返回字典里扫描出第一个 .mp4 视频直链"""
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, str) and v.startswith("http") and ".mp4" in v:
                    return v
                if isinstance(v, dict):
                    found = ModelGateway._extract_mp4(v)
                    if found:
                        return found
        return ""

    def _agnes_video(self, api_key: str, base_url: str, image_url: str, prompt: str, max_wait: int = 300):
        """Agnes 异步图生视频：创建任务 -> 轮询直至完成，返回 mp4 直链，失败返回 None。
        对 Agnes 偶发的「Internal generation failed」终态失败做【整次重试】(最多 2 次)，显著提高出片成功率。"""
        if self._is_host_broken(base_url):
            return None
        import requests
        import time
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        base = base_url.rstrip('/')
        gen_attempts = 2
        for gen_attempt in range(gen_attempts):
            try:
                body = {"model": self.agnes_video_model, "prompt": prompt}
                if image_url:
                    body["image_url"] = image_url
                # 创建任务对瞬时网络抖动退避重试(Agnes 端也偶发 Read timeout / 连接重置)
                r = None
                for attempt in range(2):
                    try:
                        r = requests.post(base + "/video/generations", json=body, headers=headers, timeout=40, proxies=self._proxies_for(base_url))
                        break
                    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                            requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError) as ce:
                        if attempt < 1:
                            logger.debug(f"[ModelGateway] Agnes 视频创建瞬时抖动重试: {str(ce)[:90]}")
                            time.sleep(2)
                            continue
                        raise
                if r.status_code != 200:
                    logger.debug(f"[ModelGateway] Agnes 视频创建未通过 {r.status_code}: {r.text[:200]}")
                    return None
                j = r.json()
                task_id = j.get("task_id") or j.get("id")
                if not task_id:
                    return None
                self._note_host_ok(base_url)  # 创建成功=该域名可达，清零失败计数
                logger.info(f"[ModelGateway] Agnes 视频任务已创建: {task_id}，开始轮询...")
                waited = 0
                interval = 6
                while waited < max_wait:
                    time.sleep(interval)
                    waited += interval
                    try:
                        poll = requests.get(base + f"/video/generations/{task_id}", headers=headers, timeout=30, proxies=self._proxies_for(base_url))
                        d = poll.json().get("data", {})
                    except Exception as pe:
                        logger.debug(f"[ModelGateway] Agnes 视频轮询抖动(任务仍在生成中)，重试: {str(pe)[:120]}")
                        continue
                    inner = d.get("data", {}) if isinstance(d.get("data"), dict) else {}
                    top = str(d.get("status", "")).upper()
                    ist = str(inner.get("status", "")).lower()
                    if top in ("SUCCESS", "SUCCEED", "SUCCEEDED") or ist in ("completed", "succeeded", "success"):
                        url = self._extract_mp4(inner) or self._extract_mp4(d)
                        if url:
                            self._note_host_ok(base_url)
                            logger.info(f"[ModelGateway] Agnes 视频生成成功: {url[:70]}...")
                            return url
                        logger.error("[ModelGateway] Agnes 视频已完成但未找到 mp4 直链")
                        return None
                    if top in ("FAILURE", "FAIL", "FAILED", "ERROR") or ist in ("failed", "error"):
                        reason = str(d.get('fail_reason') or inner.get('error') or "")
                        if gen_attempt < gen_attempts - 1:
                            # Agnes 偶发「Internal generation failed」等瞬时终态：整次重试，不放弃
                            logger.info(f"[ModelGateway] Agnes 视频生成失败({reason[:50]})，整次重试 {gen_attempt + 2}/{gen_attempts}…")
                            break
                        logger.error(f"[ModelGateway] Agnes 视频生成失败: {reason}")
                        return None
                else:
                    # while 正常结束(未 break)=超时
                    logger.debug(f"[ModelGateway] Agnes 视频生成超时 ({max_wait}s)")
                    return None
            except Exception as e:
                logger.debug(f"[ModelGateway] Agnes 视频接口异常(将自动降级): {str(e)[:160]}")
                if isinstance(e, requests.exceptions.ConnectionError):  # SSL/连接失败=主机不可达；读超时(ReadTimeout)不算
                    # 仅熔断当前域名，避免连累其它可达厂商
                    self._mark_host_broken(base_url)
                return None
        return None

    def _load_sd2_optimizer_prompt(self) -> str:
        """Load sd25-pe first, falling back to the bundled older optimizer."""
        if self._sd2_opt_prompt_cache is not None:
            return self._sd2_opt_prompt_cache
        from pathlib import Path

        backend_root = Path(__file__).resolve().parents[2]
        configured = (os.getenv("SD25_PE_SKILL_PATH") or "").strip()
        candidates = []
        if configured:
            candidates.append(Path(configured).expanduser() / "SKILL.md")
        candidates.extend([
            Path.home() / ".agents" / "skills" / "sd25-pe" / "SKILL.md",
            Path.home() / "Desktop" / "sd25-pe" / "SKILL.md",
            backend_root / "skills" / "sd25-pe" / "SKILL.md",
            backend_root / "skills" / "seedance2-prompt-optimizer" / "SKILL.md",
        ])
        text = ""
        for path in candidates:
            try:
                if path.is_file():
                    text = path.read_text(encoding="utf-8")
                    logger.info(f"[ModelGateway] 已载入视频提示词编译 Skill: {path.parent.name}")
                    break
            except OSError as exc:
                logger.warning(f"[ModelGateway] 视频提示词 Skill 读取失败: {type(exc).__name__}")
        self._sd2_opt_prompt_cache = text
        return text

    def optimize_video_prompt(self, raw_prompt: str, mode: str = "first_frame", asset_hint: str = "") -> str:
        """用 Seedance 2.0 多模态文本模型 (doubao-seed-2-0-pro) + sd2-pe 规范，把"形容词堆砌"的原始
        提示词重写为工程化指令。失败/未启用时原样返回 raw_prompt。"""
        if not self.seedance_prompt_opt or not raw_prompt or not raw_prompt.strip():
            return raw_prompt
        sd2 = self._load_sd2_optimizer_prompt()
        if not sd2:
            return raw_prompt
        candidates = []
        if self.seedance_text_model and self._is_valid_key(self.seedance_key):
            candidates.append((self.seedance_key, self.seedance_base_url, self.seedance_text_model))
        if self._is_valid_key(self.deepseek_key):
            candidates.append((self.deepseek_key, self.deepseek_base_url, self.deepseek_model_name))
        if self._is_valid_key(self.agnes_key):
            candidates.append((self.agnes_key, self.agnes_base_url, self.agnes_model_name))
        mode_hint = {
            "first_frame": "图生视频-首帧 (已提供首帧图 @图片1)",
            "first_last_frame": "图生视频-首尾帧 (已提供 @图片1 首帧、@图片2 尾帧)",
            "text_to_video": "文生视频 (无参考素材)",
            "multi_ref": "多模态参考生视频 (已提供多张参考图/视频/音频)",
        }.get(mode, "图生视频-首帧")
        sys_prompt = (
            sd2 + "\n\n## 当前调用约定\n"
            f"- 任务模式：{mode_hint}。{asset_hint}\n"
            "- 这是单镜头、单一连续动作的简单视频；保持素材逐份职责、主体映射、事件开始/结束状态与对白账本。\n"
            "- 画幅、总时长、分辨率、帧率和声音开关属于接口参数，不写入 Prompt。\n"
            "- 直接只输出优化后提示词那一段工程化中文提示词正文本身，"
            "不要输出优化问题/相关原则/任何标题/解释/Markdown，不要加引号或代码块。"
        )
        user_prompt = f"请按已加载的 Seedance 2.5 Prompt Optimizer 规则编译下面的视频提示词：\n{raw_prompt}"
        for key, b_url, model_id in candidates:
            txt = self._http_chat(key, b_url, model_id, sys_prompt, user_prompt, timeout=40)
            if txt and txt.strip():
                out = txt.strip().strip('`').strip()
                out = re.sub(r'^(优化后提示词[:：]?|【优化后提示词】)\s*', '', out).strip()
                if len(out) >= 8:
                    logger.info(f"[ModelGateway] Seedance2 提示词已优化 ({len(raw_prompt)}->{len(out)}字)")
                    return out
        return raw_prompt

    # Seedance 2.0 风格锚定：所有镜头强制写实电影质感，显式排除动画/卡通/插画/草图，
    # 既满足 Ark 对 text 内容必含 'style_caption' 的协议要求，又从风格层面杜绝"动画视频"。
    DEFAULT_STYLE_CAPTION = (
        "真实电影质感，实拍写真，photorealistic live-action cinematic film still, "
        "real human skin texture, natural lighting, 35mm film grain, shallow depth of field; "
        "绝非动画、绝非卡通、绝非3D渲染、绝非插画、绝非草图 (not anime, not cartoon, not 3d render, "
        "not illustration, not sketch, not concept art)"
    )

    def _ark_video(self, api_key: str, base_url: str, prompt: str,
                   first_frame: str = None, last_frame: str = None,
                   ref_images: list = None, ref_videos: list = None, ref_audios: list = None,
                   resolution: str = "720p", duration: int = 5, ratio: str = "9:16",
                   style_caption: str = None, max_wait: int = 360,
                   model_name: str | None = None):
        """火山 Ark (Seedance 2.0) 异步生视频：遵循 Ark contents/generations/tasks 协议，支持
        文生视频 / 图生视频-首帧 / 图生视频-首尾帧 / 多模态参考(图0-9 视频0-3 音频0-3) 全部能力。

        关键：Seedance 2.0 的请求体与 1.x 不同 ——
          · resolution / duration / ratio / watermark 是【顶层字段】，不再是 text 里的 `--flags`；
          · text 内容对象必须携带 `style_caption` 字段 (否则报 InvalidParameter.BodyFormat
            『it must contain style_caption field』)，该字段用于全局风格锚定，这里固定写实。
        """
        # 仅对 Ark 域名做熔断判定 (不读全局 _network_broken)：避免 Agnes/DeepSeek 的网络抖动
        # 把 Ark 也一起短路，从而保证图生视频命中审核后的「自愈降级」重试仍能打到 Ark。
        if self._is_host_broken(base_url):
            return None
        try:
            import requests
            import time
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            base = base_url.rstrip('/')
            sc = style_caption or self.DEFAULT_STYLE_CAPTION
            # text 内容对象：干净提示词 + 必填 style_caption (风格锚定写实)
            content = [{"type": "text", "text": prompt, "style_caption": sc}]
            # 首帧 / 尾帧 (图生视频-首帧 / 首尾帧)
            if first_frame:
                content.append({"type": "image_url", "image_url": {"url": first_frame}, "role": "first_frame"})
            if last_frame:
                content.append({"type": "image_url", "image_url": {"url": last_frame}, "role": "last_frame"})
            # 多模态参考素材 (参考图 0-9 / 参考视频 0-3 / 参考音频 0-3)
            for u in (ref_images or [])[:9]:
                content.append({"type": "image_url", "image_url": {"url": u}, "role": "reference_image"})
            for u in (ref_videos or [])[:3]:
                content.append({"type": "video_url", "video_url": {"url": u}, "role": "reference_video"})
            for u in (ref_audios or [])[:3]:
                content.append({"type": "audio_url", "audio_url": {"url": u}, "role": "reference_audio"})
            # Seedance 2.0 顶层参数：分辨率/时长/比例为独立字段；成片不打可见水印
            body = {
                "model": model_name or self.seedance_model_name,
                "content": content,
                "resolution": resolution,
                # Seedance 2.0 单次时长合法区间 4~15s，钳制避免分段出现越界值(如 3s)被 400 拒
                "duration": max(4, min(15, int(duration))),
                "ratio": ratio,
                "watermark": False,
            }
            proxies = self._proxies_for(base_url)
            # 创建任务对瞬时 TLS/连接抖动退避重试(本机到 Ark 的 TLS 会间歇性被重置)，耗尽才上抛熔断
            r = None
            create_attempts = 2
            for attempt in range(create_attempts):
                try:
                    r = requests.post(base + "/contents/generations/tasks", json=body, headers=headers, timeout=40, proxies=proxies, verify=self.tls_verify)
                    break
                except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError) as ce:
                    if attempt < create_attempts - 1:
                        logger.debug(f"[ModelGateway] Ark 视频创建瞬时抖动第{attempt+1}次重试: {str(ce)[:90]}")
                        time.sleep(min(2 * (attempt + 1), 4))
                        continue
                    raise
            if r.status_code not in (200, 201):
                # 已移除「疑似真人」特判：任何创建失败(含内容风控 400)统一静默返回 None，
                # 由上层无缝降级到 Agnes 图生视频(接受真人脸)，不再刷屏、不再走专门的疑似真人降级分支。
                logger.debug(f"[ModelGateway] Ark 视频创建未通过 {r.status_code}: {r.text[:200]}")
                return None
            task_id = r.json().get("id")
            if not task_id:
                return None
            logger.info(f"[ModelGateway] Ark 视频任务已创建: {task_id} (ratio={ratio}, {resolution}, {duration}s)，开始轮询...")
            waited = 0
            interval = 6
            poll_errs = 0  # 轮询期瞬时网络抖动计数：任务已提交成功(主机本就可达)，单次轮询失败绝不放弃也不熔断
            while waited < max_wait:
                time.sleep(interval)
                waited += interval
                try:
                    poll = requests.get(base + f"/contents/generations/tasks/{task_id}", headers=headers, timeout=30, proxies=proxies, verify=self.tls_verify).json()
                except Exception as pe:
                    # 轮询抖动：任务正在服务端生成，稍后重试；连续多次才认输，且不调用 _mark_host_broken (创建已证明可达)
                    poll_errs += 1
                    logger.debug(f"[ModelGateway] Ark 轮询抖动第 {poll_errs} 次(任务 {task_id} 仍在生成中)，重试: {str(pe)[:90]}")
                    if poll_errs >= 15:
                        logger.error(f"[ModelGateway] Ark 轮询连续 {poll_errs} 次失败，放弃任务 {task_id}")
                        break
                    continue
                poll_errs = 0
                status = str(poll.get("status", "")).lower()
                if status == "succeeded":
                    url = (poll.get("content", {}) or {}).get("video_url") or self._extract_mp4(poll)
                    if url:
                        self._note_host_ok(base_url)
                        logger.info(f"[ModelGateway] Ark 视频生成成功: {url[:70]}...")
                        return url
                    logger.error(f"[ModelGateway] Ark 视频成功但无 video_url: {str(poll)[:200]}")
                    return None
                if status in ("failed", "canceled", "cancelled", "error"):
                    err_msg = str(poll.get("error") or poll.get("message") or "").lower()
                    # 已移除「疑似真人」特判：失败统一静默返回 None，由上层降级到 Agnes 图生视频。
                    logger.debug(f"[ModelGateway] Ark 视频生成未通过: {err_msg}")
                    return None
            logger.debug(f"[ModelGateway] Ark 视频生成超时 ({max_wait}s)")
        except Exception as e:
            logger.debug(f"[ModelGateway] Ark 视频接口不可达(将自动降级): {str(e)[:160]}")
            if isinstance(e, requests.exceptions.ConnectionError):  # SSL/连接失败=主机不可达；读超时(ReadTimeout)不算
                # 仅熔断 Ark 这一个域名，不影响其它厂商，也不阻断本次的文生视频自愈兜底
                self._mark_host_broken(base_url)
        return None

    def generate_random_name(self, title: str, is_villain: bool = False) -> str:
        """
        基于选题的MD5哈希，稳定且随机地组装原创角色名字，确保完全无模板去人名
        """
        import hashlib
        h = int(hashlib.md5(title.encode('utf-8')).hexdigest(), 16)
        
        surnames = ["叶", "林", "顾", "苏", "萧", "沈", "陆", "周", "云", "楚", "姜", "秦", "白", "慕容", "上官", "司徒"]
        names = ["凡", "野", "溪", "舒", "渊", "雨", "尘", "风", "逸", "羽", "寒", "月", "澜", "天", "歌", "痕"]
        
        v_surnames = ["王", "赵", "李", "张", "高", "年", "金", "钱", "孙", "郑", "何", "黄"]
        v_names = ["天华", "霸天", "建国", "大少", "梅", "贵妃", "无赖", "强", "成", "雄", "彪", "龙"]
        
        if is_villain:
            s = v_surnames[h % len(v_surnames)]
            n = v_names[(h // len(v_surnames)) % len(v_names)]
        else:
            s = surnames[h % len(surnames)]
            n = names[(h // len(surnames)) % len(names)]
        return s + n

    def parse_story_context(self, title: str, instruction: str = "") -> Dict[str, str]:
        """
        核心辅助方法：从用户的选题和对话指引中完全动态提取主角、对手与环境要素，杜绝硬编码角色库
        """
        # 1. 动态生成初始原创名字与场景，彻底避免硬编码
        char1 = self.generate_random_name(title, is_villain=False)
        char1_role = "核心主角"
        char2 = self.generate_random_name(title, is_villain=True)
        char2_role = "反派对手"
        location = "签字大厅"
        action = "绝地反击"
        
        # 根据大类题材对场景和动作进行大方向自适应，但名字全部保留为原创哈希名
        genre = self.get_genre(title)
        if genre == "romance":
            location = "千亿签字大厅"
        elif genre == "rebirth_revenge":
            location = "豪门签约会展"
        elif genre == "campus":
            location = "雨后学校操场"
        elif genre == "xianxia":
            location = "仙宗锁仙台"
        elif genre == "palace_intrigue":
            location = "雪落冷宫庭院"
        elif genre == "horror":
            location = "昏暗扎纸铺"
        elif genre == "sci_fi":
            location = "赛博回收工厂"
        elif genre == "overseas_us":
            location = "月圆之夜的古堡"

        # 2. 从标题中提取真实人名或名词
        # 匹配双引号、书名号或者标题中的词
        title_cleaned = re.sub(r'请帮我生成一个|请生成一个|短剧|，走完流程。|走完整个流程。', '', title)
        
        # 提取第一个实体作为主角，第二个作为对手，地点等
        # 比如：“老王在火星修脚” -> char1="老王", location="火星修脚铺"
        if "在" in title_cleaned:
            parts = title_cleaned.split("在")
            if len(parts[0]) >= 2:
                char1 = parts[0][:5].strip()
            if len(parts) > 1 and "做" in parts[1]:
                subparts = parts[1].split("做")
                location = subparts[0].strip()
                action = subparts[1].strip()
            elif len(parts) > 1:
                location = parts[1][:10].strip()
        elif "之" in title_cleaned:
            parts = title_cleaned.split("之")
            if len(parts) > 1:
                char1_match = re.search(r'我(?:是|在)([\u4e00-\u9fa5\w]+)', parts[0])
                if char1_match:
                    char1 = char1_match.group(1)[:5]
                action = parts[1][:10].strip()

        # 3. 对话指引微调重命名或修改指令解析 (例如“把主角改名叫阿星”、“反派改成王梅”)
        if instruction:
            rename_match1 = re.search(r'(?:把主角|将主角|主角)(?:改名(?:叫|为)|改为|换成|叫做|是)\s*([\u4e00-\u9fa5\w]+)', instruction)
            if rename_match1:
                char1 = rename_match1.group(1).strip()
            
            rename_match2 = re.search(r'(?:把反派|将反派|把对手|对手|反派)(?:改名(?:叫|为)|改为|换成|叫做|是)\s*([\u4e00-\u9fa5\w]+)', instruction)
            if rename_match2:
                char2 = rename_match2.group(1).strip()

            location_match = re.search(r'(?:把场景|将场景|场景|把环境|环境)(?:改(?:为|成)|换成|设定为)\s*([\u4e00-\u9fa5\w]+)', instruction)
            if location_match:
                location = location_match.group(1).strip()

        return {
            "char1": char1,
            "char1_role": char1_role,
            "char2": char2,
            "char2_role": char2_role,
            "location": location,
            "action": action
        }

    @staticmethod
    def _strip_model_preamble(text: str) -> str:
        """删除部分模型(如 Agnes-flash)在正文前自带的"自我介绍/寒暄"前缀，
        例如"我是 Agnes-2.0-Flash，由 Sapiens AI 开发。作为 AI 短剧总导演智能体，我将为您…"。
        这种前缀会污染资产正文，并让下游角色名提取错乱(把"顾寒洲出场"当成名字)。
        只剥离开头的身份/寒暄句，绝不触碰正文。"""
        if not text:
            return text
        t = text.lstrip()
        # 1) 先剥掉开头的问候/客套词 (你好/好的/当然…)
        t = re.sub(r'^\s*(?:你好|您好|嗨|哈喽|hi|hello|hey|好的|当然|没问题|收到|明白|很高兴)'
                   r'[!！,，.。、\s]*', '', t, flags=re.I).lstrip()
        # 2) 逐句剥离开头的"自我介绍/寒暄"句：句中含模型身份或"为您…"客套标记才删，
        #    遇到真正正文(markdown 标题/无寒暄标记的句子)立即停止，绝不误删正文。
        CHATTER = ('我是', '我叫', 'agnes', 'sapiens', '智能体', '大模型', '语言模型',
                   '我将为', '我会为', '我来为', '我将基于', '为您拆解', '为您打造', '为您创作',
                   '为您生成', '为您呈现', '为您带来', '很荣幸', 'developed by', 'created by', 'i am ')
        for _ in range(6):
            m = re.match(r'\s*([^。！？\n#]{0,200}?[。！？!?])\s*', t)
            if not m:
                break
            sent = m.group(1).lower()
            if any(k in sent for k in CHATTER):
                t = t[m.end():].lstrip()
            else:
                break
        # 3) 去掉残留在开头的纯分隔线
        t = re.sub(r'^\s*(?:-{3,}|={3,})\s*', '', t).lstrip()
        return t or text

    def call_llm(self, model: str, system_prompt: str, user_prompt: str, creative_title: str, director_style: str = "cyberpunk", shot_style: str = "cinematic", user_instruction: str = "") -> str:
        """
        调用大语言模型 (在线或离线动态智能故事生成算法)
        基于配置的导演风格与运镜风格，动态组合 36运镜、8种站位和 16种环境构图
        """
        # Project-wide enabled Markdown Skills are an atomic runtime snapshot.
        # They remain lower-authority creative guidance and are never executable.
        system_prompt = runtime_skill_registry.apply(system_prompt)

        # 组装用户内容 (含对话微调指引)
        full_user_content = user_prompt
        if user_instruction:
            full_user_content += (
                f"\n\n【用户最新对话修改/微调指引】：\n{user_instruction}\n"
                f"请严格根据上文已生成的资产和这一最新指引对后续内容进行修改或重构，并确保符合所有编剧导演法则（无心理描写红线、双轨节奏等）。"
            )

        # 数据库里启用的动态模型优先。模型 ID、Base URL 和解密密钥均来自
        # 运行时注册表，生产代码不维护供应商的远端模型清单。
        runtime = runtime_model_registry.resolve(model, "text")
        if runtime is None and not (model or "").strip():
            runtime = runtime_model_registry.first_for_category("text")
            if runtime:
                model = runtime.model_ids[0]
        if runtime:
            text = self._http_chat(
                runtime.api_key,
                runtime.base_url,
                model,
                system_prompt,
                full_user_content,
            )
            if text:
                logger.info(
                    "[ModelGateway] 动态文本模型生成成功 (provider=%s, model=%s)",
                    runtime.provider,
                    model,
                )
                return self._strip_model_preamble(text)

        # 1. 在线调用：构建多 provider 降级链 (所选优先 -> Agnes -> deepseek -> qwen -> gemini)
        #    所选 provider 在可直连环境(如国内)优先生效；不可达时自动降级到其它已配置有效的真实模型
        primary = self._detect_provider(model, default="deepseek")
        order = [primary, "agnes", "deepseek", "qwen", "gemini"]
        tried = set()
        for name in order:
            if name in tried:
                continue
            tried.add(name)
            key, b_url, api_model = self._provider_creds(name)
            # seedance(火山ark) 的模型是视频模型，不适合做文本生成，跳过文本降级
            if name == "seedance":
                continue
            if not self._is_valid_key(key):
                continue
            text = self._http_chat(key, b_url, api_model, system_prompt, full_user_content)
            if text:
                text = self._strip_model_preamble(text)
                logger.info(f"[ModelGateway] 文本生成成功 (provider={name}, model={api_model})")
                return text

        logger.warning("[ModelGateway] 所有在线文本 provider 均不可用，平滑退回离线引擎")

        # 2. 离线模式：全动态、不需要预先设置模板的智能故事生成算法
        # 提取动态上下文实体
        ctx = self.parse_story_context(creative_title, user_instruction)
        char1 = ctx["char1"]
        char2 = ctx["char2"]
        location = ctx["location"]
        
        # 确定导演风格光影修饰词
        if director_style == "cyberpunk":
            lighting = "霓虹冷色频闪，高对比度明暗 Chiaroscuro 对峙，冷蓝色温与猩红色温对撞"
            visual_term = "赛博朋克深冷调 (Deep Cyan & Neon Red)"
        elif director_style == "retro":
            lighting = "伦勃朗光 (Rembrandt Lighting) 脸颊亮区，黄金时刻逆光 (Golden hour backlight)，暖黄色调"
            visual_term = "怀旧胶片风格 (Golden Warm Film Style)"
        elif director_style == "sci_fi_future":
            lighting = "冷金属硬质反光，幽蓝色全息投影微光，超高色温冷白强背光"
            visual_term = "科幻未来极冷调 (Sci-Fi Holographic Style)"
        elif director_style == "palace":
            lighting = "红墙黛瓦古典自然散射光，金色屋脊漫反射，深红与暗金暖色调"
            visual_term = "古风宫廷优雅调 (Traditional Palace Style)"
        elif director_style == "mystery_dark":
            lighting = "极端弱光与大面积黑影，局部蜡烛微弱暖光，剪影明暗对峙"
            visual_term = "悬疑黑色电影调 (Dark Film Noir Style)"
        elif director_style == "anime":
            lighting = "明亮动漫自然天光，高饱和色彩漫反射，梦幻丁达尔边缘光"
            visual_term = "动漫二次元色彩调 (Niji Anime Style)"
        elif director_style == "horror_folk":
            lighting = "民俗高饱和红绿高对比冷光频闪，香烛惨白冷光，诡异阴沉黑调"
            visual_term = "民俗惊悚诡秘调 (Folk Horror Tone)"
        else:
            lighting = "丁达尔效应/体积光 (Tyndall Effect)，金属玻璃硬质反光，电影级自然光照"
            visual_term = "大片级写实硬核调 (Cinematic Reality Style)"


        # 随机挑选运镜、站位、构图
        blocking = self.BLOCKING_STANDS[0] if shot_style != "cinematic" else random.choice(self.BLOCKING_STANDS)
        comp_1 = random.choice(self.COMPOSITIONS)
        comp_2 = random.choice(self.COMPOSITIONS)
        
        shot_1_mov = "Extreme Close-up Dolly" if shot_style == "cinematic" else "Slow Dolly In"
        shot_3_mov = "Dolly Zoom" if shot_style == "cinematic" else "Lateral Tracking"

        genre = self.get_genre(creative_title)
        genre_desc = f"{genre}类型热播短剧，主要面向抖音快手及视频号受众，强调高对比冲突与反差"
        
        # 动态对白配音文本，包含模式打破 (Pattern Interrupt) 元素
        speech_char2 = "你不过是个无权无势的底层小人物，也配站在这里？！"
        speech_char1 = "睁大眼看清楚，这才是我的底牌！今日，属于我的一切我都会拿回来！"
        
        # 根据题材匹配特定台词与语调
        if genre == "xianxia":
            speech_char2 = "萧凡，你已全身筋脉尽碎，交出魔骨，仙门容不得你！"
            speech_char1 = "清虚老儿！你们道貌岸然剥我仙骨，今日我便一剑踏平你这仙山！"
        elif genre == "romance":
            speech_char2 = "顾安然，你只是个被扫地出门的养女，这设计稿你不配署名！"
            speech_char1 = "陆霆骁是我的底气，但没有他，我也能让你们身败名裂！"
        elif genre == "horror":
            speech_char2 = "林九，半夜扎纸铺不迎活客？今天我就砸了你这纸人店！"
            speech_char1 = "人有归路，鬼有黄泉。赵虎，这副大木黑漆棺，是留给你的！"

        # 针对不同智能体阶段，返回纯动态的生成结果
        if "编剧" in system_prompt or "writer-agent" in system_prompt:
            return f"""【场景1：{location}入口 / 日 / 高对比度 {lighting}】
情节节奏：紧 ；情感节奏：重 ；预估时长：35秒

描述：{char1}独自站立在{location}门口，细雨落在他肩膀的深色风衣上。
{char2}带着手下在一旁高调拦路，手里抓着撕成两半的公文，随手甩在{char1}脚边。
{char2}斜眼冷笑，满面不屑。
{char1}一言不发，神色平静，右指捏紧了风衣衣角，毫无退意。
对白：
{char2}：{speech_char2}
环境空间 Blocking 调度：采用了 **{blocking}** 与 **{comp_1}**。

【场景2：{location}会场内 / 日 / {visual_term}】
情节节奏：松 ；情感节奏：轻 ；预估时长：45秒

描述：{char1}在大厅内慢步前行，环视四周。
台下突然发生骚动，背景大屏幕开始闪烁红色的安全警报，显示出关键反转数据。
{char2}脸色突然由狂妄转为浮肿的惨白，穿着高跟鞋连连倒退两步，撞翻了身后的水晶酒杯。
{char1}淡淡看着对方，嘴角勾起一丝冷峻的弧度。

【场景3：{location}台前 / 日 / 聚光灯汇聚】
情节节奏：紧 ；情感节奏：重 ；预估时长：40秒

描述：{char1}拿出一枚金色质感的修罗令（或核心文件），用力按在演讲台上。
大理石台面瞬间震落了杯盏，全场保全人员齐刷刷向{char1}低头行礼。
{char2}软瘫在碎玻璃渣中，手指止不住地颤抖。
{char1}站在高高的石阶上，俯视着瘫倒的对手，神色如铁石一般坚冷。
对白：
{char1}：{speech_char1}
环境空间 Blocking 调度：采用了 **{comp_2}**。"""

        elif "总导演" in system_prompt or "executive-director" in system_prompt:
            return f"""### 核心卖点
- 题材与目标平台：{genre_desc}
- 核心爽点/虐点/笑点：底层绝地逆袭，揭穿对手虚伪面具，实力悬殊下的翻盘
- 前 2 秒 Hook 定位：【Pattern Interrupt 模式打破】民政局/发布会门口，十辆黑金劳斯莱斯车队死死围住大门，雨水在半空中发生倒流

### 结构大纲
- 核心冲突：{char1}被{char2}强行剥夺地位与资产，{char1}在关键签字会场逆天打脸，唤醒沉眠背景夺回主控权
- 三幕结构：
  - 开端：{location}入口冲突爆发，{char1}被肆意羞辱，前2秒流量钩子触发
  - 发展：{location}大厅博弈，警报红灯大作，底牌线索悄然铺垫
  - 高潮：{char1}扔出终极物证（修罗令/遗诏/加密数据），全场保全倒戈，{char2}瘫软倒地
  - 结局：{char1}功成身退，背影融入黑伞与大雨，留给江州一个无声的传说"""

        elif "角色设计师" in system_prompt or "character-designer" in system_prompt:
            # 响应“看板展示大厅 无需预先设置任何 角色构建”
            # 直接返回全动态的 Markdown 角色设计文本，无需任何硬编码的“主角”和“反派”区分框
            return f"""### 角色造型与五维 DNA 锁定方案

#### 👨‍🎤 核心角色：{char1} (执行逆袭的主体)
- **面部**：剑眉星目，左眼下方有一颗不易察觉的泪痣，`consistent facial structure`，`locked face identity`。
- **发型**：干练利落的黑色碎发，略带一点凌乱，保持跨镜头发型一致。
- **体型**：九头身，体型偏瘦，身高180cm，在风雨中身姿依然坚挺拔。
- **服饰**：身穿经典款黑色长风衣，里面搭配一件净白 T 恤，左手食指戴单枚素银戒指。
- **表情眼神**：眼神冷峻深邃，嘴角常挂着一抹看似克制而冷漠的微笑。

#### 🦹 对手角色：{char2} (阻碍力量的化身)
- **面部**：颧骨突出，双眼狭长，眼神中闪烁着傲慢与隐约的癫狂。
- **发型**：打理得一丝不苟的油光背头，发丝紧贴，泛着冰冷的胶水质感。
- **体型**：身材发福，神色傲慢，走起路来带有习惯性的居高临下感。
- **服饰**：配戴奢华大金链与名贵腕表，身穿一套灰色奢华条纹西装，歪系着领带。
- **表情眼神**：表情浮肿，经常斜视主角，咬牙切齿时两颊肌肉明显抽搐。"""

        elif "分镜师" in system_prompt or "storyboard-artist" in system_prompt:
            # 返回标准的 9 列 Markdown 分镜表，完全动态且符合 shooting-guide 15s 节奏
            return f"""镜号 | 景别 | 机位角度 | 运镜 | 画面内容 | 台词对白 | 声音 | 时长 | 叙事目的
1 | 全景 | 平视 | Establishing Shot | {char1}撑伞站在{location}入口，大雨滂沱打湿衣角。 | | 风雨声与凄凉古风琴声 | 3秒 | 交代场景与整体氛围，建立开端
2 | 中景 | 仰视 | {shot_1_mov} | {char2}指着{char1}的鼻子肆意嘲讽，保镖在身侧列队合围。 | “{speech_char2}” | 嘈杂雨声与反派狂笑 | 6秒 | 引入冲突，展示角色站位与阻碍力量
3 | 近景 | 俯视 | {shot_3_mov} | {char1}猛地一扬手扔出金色令徽，{char2}惊恐倒退撞翻酒架。 | “{speech_char1}” | 震撼雷鸣声，摇滚重低音BGM瞬间起燃 | 6秒 | 动作高潮与正义翻盘，动作收尾留悬念"""

        elif "宣发" in system_prompt or "pr-agent" in system_prompt:
            # 宣发引流文本
            pr_title = f"{creative_title}：隐藏大佬的暴爽翻盘！"
            pr_body = "太爽了！前妻/恶毒总监当众撕毁签字合同，逼迫主角净身出户！殊不知主角就是身家千亿的龙王/总裁，一通电话全省财阀大雨中跪迎！逆袭风暴点爆全场，点击免费看全集！💥"
            
            if genre == "xianxia":
                pr_title = "《仙骨已碎，剑开天门！》"
                pr_body = "虚伪仙尊强挖去我的魔骨给义子？他没想到我竟然唤醒了体内的九幽魔皇元神，当着全天下宗门弟子的面一剑震碎仙山！热血仙侠狂暴反扑！点击免费看大结局！"
            elif genre == "horror":
                pr_title = "《深夜纸人抬棺：民俗禁忌起！》"
                pr_body = "深夜恶霸强行抢夺扎纸铺的玉佛，少掌柜默默摇动三清铜铃，满屋纸扎童男童女瞬间走下货架列队抬棺！惊悚重重，点击免费看爆爽灵异大戏！💥"
                
            return f"""【封面大字PR标题】
🔥 《{pr_title}》

【黄金引流文案】
📌 ‘{pr_body}’"""

        return "*(AI 智能内容生成完成)*"

    @staticmethod
    def _sanitize_prompt_for_agnes(prompt: str) -> str:
        """Agnes 网关内容审核对 DEID 负面词(换脸/畸形/passport/非真人)与暴力词敏感，会 400 content_policy。
        而 Agnes 本就接受写实人脸、无需 DEID 去脸(那是火山 Ark 疑似真人专用)。故走 Agnes 时清洗掉
        括号负面约束块与触发词，只保留正向写实描述，确保 Agnes 文生图/图生视频不被拒。"""
        p = prompt or ""
        # 去掉成对括号(中/英)内的负面约束/DEID 说明，最多三层嵌套
        for _ in range(3):
            p = re.sub(r'[（(][^（()）]*[)）]', '', p)
        # 删除以 避免/严禁/不要 等引导、直到句末的负面从句
        p = re.sub(r'(避免|严禁|不要|不得|杜绝)[^。.;；\n]*[。.;；\n]?', '', p)
        # 删除已知触发内容审核的词 (DEID 身份词 / 身体畸变词 / 戏剧暴力与冲突词)
        for kw in ["换脸", "脸部变形", "手部畸形", "多余手指", "passport photo", "headshot",
                   "not a real person", "not a real celebrity", "真实名人", "可识别的个人身份",
                   "血泊", "血", "尸体", "暴力", "gore", "blood", "打脸", "渣男", "复仇", "报仇",
                   "癫狂", "羞辱", "厮杀", "杀", "死", "尸", "拳", "踹", "扇", "撕"]:
            p = p.replace(kw, "")
        p = re.sub(r'\s+', ' ', p).strip(" ，,。.；;")
        # Agnes 对超长提示词(如嵌 3000 字五视图模板)易判违规，截断到稳妥长度，保留前部核心描述
        if len(p) > 600:
            p = p[:600]
        return p

    def _enhancePromptWithRules(self, prompt: str) -> str:
        """
        根据影视级表现力规约（色彩调色、微表情情绪、背景自愈、道具特效），自动对提示词进行深度物理层增强。
        """
        if not prompt or not prompt.strip():
            return prompt

        enhanced = prompt
        lowerPrompt = prompt.lower()

        # 1. 角色微表情情绪控制引擎 (面部肌肉微反应增强)
        # NOTE: 规避 AI "面瘫呆滞恐怖谷"，将抽象情绪词翻译为具体的眼眶、嘴唇、下巴肌肉协同微动作描述。
        expressionMap = {
            "sad_crying": (
                ["哭", "泪", "悲伤", "伤心", "痛苦", "哀伤", "cry", "sad", "pain", "grief", "weeping"],
                "lower eyelids slightly swollen and red, tears welling in the bottom of eyes, under-lip tensed and gently bitten by teeth, subtle chin muscles trembling"
            ),
            "angry_fierce": (
                ["怒", "愤怒", "咆哮", "狰狞", "杀气", "生气的", "angry", "fierce", "rage", "furious", "teeth gritted"],
                "eyebrows knitted together tightly forming deep vertical wrinkles, nostrils flaring slightly, corners of the mouth pulled downward and tensed, teeth gritted, intense fierce glare"
            ),
            "shocked_scared": (
                ["惊", "震惊", "恐惧", "害怕", "颤抖", "惊恐", "shocked", "scared", "fear", "terrified", "shivering"],
                "pupils dilated, eyelids wide open, mouth slightly agape, Adam's apple slowly bobbing, subtle body shivering under light"
            ),
            "joyful_smirking": (
                ["笑", "喜悦", "奸笑", "狂妄", "邪魅", "自信的", "smirk", "smile", "joy", "laugh", "arrogant", "confident grin"],
                "one eyebrow slightly arched, single corner of the mouth curved upward in a smirking grin, gaze full of contempt, confident expression"
            ),
            "contemplative_silent": (
                ["忍", "克制", "沉思", "沉默", "忧郁", "refrain", "contemplative", "silent", "brooding", "suppressed"],
                "gaze downward and wandering, lips pressed tightly in a thin line, facial muscles slightly rigid and tense"
            )
        }

        for expKey, (keywords, facialDesc) in expressionMap.items():
            if any(kw in lowerPrompt for kw in keywords):
                if facialDesc not in enhanced:
                    enhanced += f", {facialDesc}"
                    break

        # 2. 电影级色彩与调色矩阵 (色彩基调智能判断)
        # NOTE: 拒绝用空洞的 "cinematic"，依据情节冲突性质与环境词自动推荐经典影调风格。
        colorMap = {
            "teal_orange": (
                ["打斗", "格斗", "武打", "对决", "交锋", "出拳", "踢", "剑", "刀", "兵器", "fight", "clash", "punch", "kick", "sword", "blade", "combat", "action scene"],
                "Teal and Orange color grading, high contrast cinema grading, warm highlights and cool cyan shadows, cinematic blockbuster look"
            ),
            "muted_greens": (
                ["雨", "雪", "阴天", "冷", "杀", "死", "悲", "克制", "rain", "snow", "cold", "kill", "sad", "refrain", "bleach bypass"],
                "bleach bypass film style, desaturated colors, muted mossy greens and cold blue tones, raw film texture"
            ),
            "golden_hour": (
                ["阳光", "温暖", "温馨", "黄昏", "傍晚", "回忆", "sunlight", "warm", "golden hour", "sunset", "evening", "memory"],
                "Golden Hour lighting, warm sunset glowing hues, soft orange light rays, Kodak Portra 400 film tones"
            ),
            "neon_magenta": (
                ["都市", "繁华", "赛博", "霓虹", "酒吧", "街头", "city", "neon", "cyber", "bar", "street", "midnight"],
                "neon color scheme, vibrant teal and magenta reflected glow on wet ground, cross-processed colors, cyber atmosphere"
            ),
            "sodium_vapor": (
                ["废墟", "荒凉", "废土", "历史", "古老", "ruin", "wasteland", "desert", "ancient", "historical"],
                "sodium vapor monochromatic tones, deep high-contrast dark-yellow lighting, gritty rusty textures"
            )
        }

        hasColor = False
        for colKey, (keywords, colorDesc) in colorMap.items():
            if any(kw in lowerPrompt for kw in keywords):
                if colorDesc not in enhanced:
                    enhanced += f", {colorDesc}"
                    hasColor = True
                    break

        if not hasColor:
            defaultColor = "film color graded, natural volumetric movie lighting"
            if defaultColor not in enhanced:
                enhanced += f", {defaultColor}"

        # 3. 道具与光影特效增强
        # NOTE: 对飞剑、魔印、法宝等玄幻男频道具及常规武器做材质与能量光效的视觉扩音器。
        propMap = {
            "flying_sword": (
                ["飞剑", "flying sword"],
                "metallic flying sword floating in mid-air, ancient runes glowing on the blade, surrounded by crackling electric sparks, kinetic wind distortion trails"
            ),
            "demon_seal": (
                ["魔印", "上古魔印", "demon seal", "magic stamp"],
                "rough black basalt seal with flowing magma-red molten runes, emitting dark volumetric smoke, micro space fissures warping the background"
            ),
            "magic_circle": (
                ["法宝", "法阵", "阵法", "magic circle", "astrolabe", "talisman"],
                "rotating miniature gold astrolabe, galaxy-like stardust swirling inside, projection of transparent colored magic circles"
            ),
            "common_blade": (
                ["剑", "刀", "兵器", "金属", "sword", "blade", "weapon", "metal parry"],
                "sharp metallic gleam, volumetric light reflection on steel, parry sparks suspended, kinetic wind distortion"
            )
        }

        for propKey, (keywords, propDesc) in propMap.items():
            if any(kw in lowerPrompt for kw in keywords):
                if propDesc not in enhanced:
                    if propKey == "common_blade" and ("flying_sword" in enhanced or "飞剑" in lowerPrompt):
                        continue
                    enhanced += f", {propDesc}"
                    break

        # 4. 高级光影雕刻注入 (轮廓光/体积光)
        # NOTE: 针对打斗或暗色场景，自动增加背光、轮廓边缘光与体积光增强立体度。
        if any(kw in lowerPrompt for kw in ["clash", "fight", "strike", "dark", "night", "shadow", "格斗", "打斗", "黑夜", "暗"]):
            rimLight = "sharp intense rim light outlining the figure's silhouette, strong contrast, dark shadow depth"
            if rimLight not in enhanced:
                enhanced += f", {rimLight}"

        # 5. 背景自愈与防止拉胯 (Depth of Field & Film Grain)
        # NOTE: 强制使用电影景深和细微噪点，虚化粗糙背景，消除 AI 平滑油腻的塑料质感。
        backgroundSanitizer = "cinematic depth of field, blurred bokeh background, 85mm f/1.8 lens effect, subtle organic 35mm film grain, realistic surface textures, raw photo quality"
        if "depth of field" not in lowerPrompt and "bokeh" not in lowerPrompt:
            enhanced += f", {backgroundSanitizer}"

        return enhanced

    def generate_image(self, model: str, prompt: str, ref_images: list = None, size: str = None):
        """
        调用文生图大模型，返回 (图片URL, 实际使用的 provider 名)。
        统一优先 Seedance/火山 Ark Seedream，保证与后续 Seedance 图生视频同源、风格画质一致。
        ref_images：角色五视图等参考图 URL 列表 (Seedream 通过 image 字段做主体参考，锁定人物一致性)。
        降级链：所选/seedance 优先 -> Agnes -> gemini -> 离线兜底图。
        """
        prompt = self._enhancePromptWithRules(prompt)
        runtime = runtime_model_registry.resolve(model, "image")
        if runtime is None and not (model or "").strip():
            runtime = runtime_model_registry.first_for_category("image")
            if runtime:
                model = runtime.model_ids[0]
        if runtime:
            reference_urls = [
                url for url in (ref_images or [])
                if isinstance(url, str) and url.startswith("http")
            ][:9]
            extra: dict[str, object] = {"n": 1, "size": size or "1024x1024"}
            if runtime.provider in {"volcengine", "seedance"}:
                extra = {
                    "response_format": "url",
                    "size": size or self.seedance_image_size,
                    "watermark": self.seedance_image_watermark,
                }
                if reference_urls:
                    extra["image"] = reference_urls
            url = self._http_image(
                runtime.api_key,
                runtime.base_url,
                model,
                prompt,
                extra=extra,
            )
            if url:
                logger.info(
                    "[ModelGateway] 动态图像模型生成成功 (provider=%s, model=%s)",
                    runtime.provider,
                    model,
                )
                return url, runtime.provider

        primary = self._detect_provider(model, default="seedance")
        # 各 provider 对应的文生图模型 ID (seedance 用 Seedream 文生图模型，而非视频模型)
        image_model = {
            "seedance": self.seedance_image_model,
            "agnes": self.agnes_image_model,
            "gemini": self.gemini_model_name,
        }
        ref = [u for u in (ref_images or []) if u and isinstance(u, str) and u.startswith("http")]
        # seedance(Seedream) 必须排最前：图生视频走 Seedance/火山 Ark 时，Ark 风控只接受
        # 火山生态自产(带 AI 标记)的首帧图；外部写实人像(如 Agnes)会被判定"疑似真人"而 400 拒绝。
        # 因此要让 Seedance 视频跑通，首帧图必须用 Seedream。Agnes 仅作文生图兜底。
        order = ["seedance", primary, "agnes", "gemini"]
        tried = set()
        for name in order:
            if name in tried or name not in image_model:
                continue
            tried.add(name)
            key, b_url, _ = self._provider_creds(name)
            if not self._is_valid_key(key):
                continue
            # 火山 Ark Seedream 需要 response_format/size/watermark 字段；其它厂商用通用字段。
            # watermark 必须为 True：Ark 图生视频靠该 AI 标记识别"火山自产 AI 图"放行，
            # 关闭会导致写实人脸首帧被判「疑似真人」而 400 拒绝 (本文件多处注释亦载明须"带 AI 标记")。
            if name == "seedance":
                extra = {"response_format": "url", "size": size or self.seedance_image_size,
                         "watermark": self.seedance_image_watermark}
                if ref:
                    # Seedream image 字段传入角色五视图作主体参考，锁定人物一致性
                    extra["image"] = ref[:9]
            else:
                extra = {"n": 1, "size": size or "1024x1024"}
            # 火山 Seedream 用原始提示词(含 DEID 过审);其它网关(Agnes/Gemini)用清洗后干净写实提示词避免内容审核 400
            use_prompt = prompt if name == "seedance" else self._sanitize_prompt_for_agnes(prompt)
            url = self._http_image(key, b_url, image_model[name], use_prompt, extra=extra)
            if url:
                logger.info(f"[ModelGateway] 文生图成功 (provider={name}, model={image_model[name]}, 参考图={len(ref)}): {url[:60]}...")
                return url, name

        # 所有在线文生图 provider 均不可用：不再按性别关键词返回任何硬编码占位图。
        # 旧逻辑会让占位图被下游当成"真实首帧"使用，污染成片。返回 None，由上层据此降级为
        # Seedance 文生视频 (text-to-video)，整条流水线仍走真实 doubao-seedance-2-0-260128 模型。
        logger.error("[ModelGateway] 所有在线文生图 provider 均不可用，本镜放弃首帧图 "
                     "(降级为 Seedance 文生视频，不使用任何占位图)")
        return None, None


    # 题材 -> 时代服饰硬约束：确保五视图人物造型契合剧情时代背景
    # (如修仙/武侠/宫斗必须古装，绝不能出现现代服饰)，从 get_genre 的题材分类推导。
    GENRE_ERA_COSTUME = {
        "xianxia": "古代仙侠时代背景，角色必须身着古装（道袍/汉服/广袖仙袍/云纹长袍），古典发髻发饰，"
                   "严禁出现西装、夹克、衬衫、牛仔裤、卫衣、手表、眼镜、手机等任何现代服饰与现代元素",
        "wuxia": "古代江湖武侠时代背景，角色必须身着古代侠客装束（劲装/长衫/披风/束发），古典发型，"
                 "严禁出现任何现代服饰、现代配饰与现代元素",
        "palace_intrigue": "古代宫廷时代背景，角色必须身着华美古装宫廷服饰（朝服/官袍/凤冠华服锦袍），古典发髻头饰，"
                           "严禁出现任何现代服饰与现代元素",
        "retro_romance": "上世纪七八九十年代怀旧时代背景，角色身着该年代感服饰发型，严禁出现当代潮流元素",
        "overseas_us": "欧美时代背景，角色为欧美人物造型与对应服饰",
    }

    # 五视图五大常见问题对照负面约束：
    # 五官漂移 / 服装走样 / 背景不一 / 手部崩塌 / 配色不稳。在五视图生成时强力规避。
    SHEET_PROBLEM_NEGATIVE = (
        "(严格规避五视图五大常见问题——"
        "①五官漂移：多视角间五官形状/比例不一；②服装走样：褶皱、配件位置在各视角紊乱不符；"
        "③背景不一：各视角背景不统一；④手部崩塌：手指数量/姿态错误、多指畸形；⑤配色不稳：颜色偏差、风格不统一。"
        "no face drift, inconsistent facial features across views, changing outfit details between views, "
        "inconsistent background, deformed hands, extra or missing fingers, color inconsistency, "
        "multiple different persons, watermark, text, logo)"
    )

    def generate_character_sheet(self, model: str, name: str, char_desc: str,
                                 dir_style: str = "cyberpunk", genre: str = "general",
                                 ref_images: list = None) -> str:
        """
        生成角色五视图设定图(角色视觉锚点，解决跨镜头人物一致性)。
        方法论遵循项目五视图人物设定板规范：人物设定卡 → 比例统一 → 结构先定 → 细节后补，
        5 个标准视角严格按正面/正面四分之三/标准侧面/背面四分之三/背面的顺序输出，
        并对照规避"五官漂移/服装走样/背景不一/手部崩塌/配色不稳"五大问题。
        genre：剧情题材(来自 get_genre)，锁定符合时代背景的服饰造型(如修仙/武侠须古装)。
        """
        # 时代服饰约束优先：题材若属古装/年代/欧美类，强制对应时代造型；否则按导演视听风格取风格词
        era_costume = self.GENRE_ERA_COSTUME.get(genre, "")
        style_word = {
            "cyberpunk": "赛博朋克写实电影感", "retro": "年代怀旧胶片质感", "palace": "古装东方美学写实影视感",
            "mystery_dark": "悬疑低饱和写实电影感", "anime": "2D日漫风格", "horror_folk": "民俗惊悚写实质感",
            "sci_fi_future": "硬核科幻写实质感",
        }.get(dir_style, "现代都市短剧写实电影感")
        # 古装/年代/欧美题材下，画质风格词不再使用"现代都市"基调，避免与时代服饰冲突
        if era_costume:
            style_word = "符合时代背景的写实影视质感"

        # 干净的描述式五视图提示词(英文为主、跨 provider 通用)：直接描述要画的画面本身。
        # 关键修复：绝不把 markdown 文档模板 / README 引用 / 中文元指令塞进文生图模型——
        # 那会被 Agnes 内容审核判 content_policy_violation 拒(Ark SSL 不可达时五视图会全失败、
        # 退化为纯文本，前端只剩文字看不到图)。五视图一致性"方法论"只喂给上游 LLM(阶段3 sys_prompt)，
        # 此处只给图像模型干净可执行的画面描述。
        era_clause = f" The character must wear period-accurate costume — {era_costume}." if era_costume else ""
        from app.core.storyboard_quality import build_five_view_prompt
        prompt = (
            build_five_view_prompt(name, f"{char_desc}.{era_clause}", style_word)
            + " photorealistic, live-action, cinematic, highly detailed, sharp focus, 35mm film. "
            + self.SHEET_PROBLEM_NEGATIVE
        )
        url, _ = self.generate_image(
            model,
            prompt,
            ref_images=ref_images,
            size=os.getenv("CHARACTER_SHEET_SIZE", "2560x1440"),
        )
        logger.info(f"[ModelGateway] 角色五视图生成 ({name}, genre={genre}): {(url or '无')[:60]}...")
        return url


    # 镜头一致性强化：正向锁定词 + 负面约束词 (供分镜底片生成时拼接)
    SHEET_LOCK_POSITIVE = (
        "严格参考角色五视图和角色状态卡，保持同一个人物身份、同一张脸、同一个发型、同一个发色、"
        "同一套服装、同一个体型、同一个年龄感和同样的标志性配饰"
    )
    SHEET_LOCK_NEGATIVE = (
        "(避免：不同人物、换脸、五官变化、发型变化、发色变化、服装变化、服装颜色变化、"
        "体型变化、年龄变化、随机配饰、多余人物、角色混淆、脸部变形、手部畸形、多余手指、文字、水印、logo)"
    )

    # 规避火山 Ark 图生视频风控 (InputImageSensitiveContentDetected「疑似真人」)。
    # 实测结论：Ark 对"清晰可识别的正面写实人脸"会判「疑似真人」拒；但"不展示清晰正面人脸"的
    # 写实电影构图(背影/逆光剪影/过肩/侧脸/面部被遮挡/环境远中景)即便保持照片级真实也放行。
    # 关键：绝不能为了过审把画面降成 3D渲染/CG/卡通(那正是用户禁止的"动画卡通")。
    # 正确做法是【保持照片级写实，只用构图把"清晰正面真人脸"从首帧里移除】—— 既写实、又过审。
    # 实在需要露正脸特写的镜头，由上层渐进式自愈降级为 Seedance 文生视频兜底(模型自造虚构人物，不受真人审核限制)。
    DEID_POSITIVE = (
        "，保持照片级写实实拍电影质感(photorealistic, live-action, cinematic film still, 35mm film grain, "
        "real human skin, natural lighting)，但采用不展示清晰可识别正面人脸的电影化构图："
        "优先人物背影、强逆光剪影、过肩后方视角、侧脸、面部转离镜头或被发丝/前景道具/阴影自然遮挡、"
        "或人物在环境中占比偏小的写实远中景；角色为虚构人物(fictional character, not a real celebrity)，"
        "画面无任何文字、无水印、无logo"
    )
    DEID_NEGATIVE = (
        "(避免：清晰可识别的正面真人脸、正脸特写、直视镜头的高锐度清晰五官、证件照/写真式人脸、"
        "护照照片、headshot、passport photo、真实名人、真实可识别的个人身份；"
        "并严禁任何非写实风格：动画、卡通、二次元、3D渲染、游戏CG、Unreal Engine、插画、漫画、概念草图 "
        "anime, cartoon, 2d/3d cartoon, 3d render, cgi, game cg, unreal engine, illustration, comic, concept art, sketch)"
    )

    # ============== 三篇提示词文档工程化落地 (可复用片段，拼进 Stage4/5 图生与视频提示词) ==============
    # 来源：场景设计提示词.md / 短剧情节与镜头连贯性提示词.md / 短剧情绪与面部表情提示词库.md
    # 作用：把"给人看的方法论"变成"每一镜可执行的正/负向约束"，直接作用于成片画面。

    # 场景设计：场景服务剧情 + 空间层次稳定 (场景设计提示词.md §最小模板/§5/§12)
    SCENE_STABILITY_POSITIVE = (
        "，场景服务剧情且空间关系固定：前景-中景-背景三层电影感纵深，主光方向与色温统一，"
        "关键道具位置固定并参与叙事，人物左右站位与画面方向稳定 "
        "(layered foreground-middle-background depth, consistent location, same room layout, "
        "same furniture and prop placement, same lighting direction and color temperature, stable composition)"
    )
    SCENE_STABILITY_NEGATIVE = (
        "(规避场景失稳：random background, cluttered composition, inconsistent room layout, "
        "changing furniture, changing props, changing lighting direction, inconsistent color tone, "
        "messy objects, empty meaningless background, no spatial depth, background flickering)"
    )

    # 镜头连贯性：六锚点 + 承接上一镜 + 逐镜单动作 (短剧情节与镜头连贯性提示词.md §1/§7/§8)
    CONTINUITY_POSITIVE = (
        "，严守跨镜连贯六锚点：同一人物同一张脸同一发型同一服装、同一场景与左右画面方向、"
        "动作从上一镜自然延续、情绪逐级递进不突变、道具始终在同一只手同一位置、光影色温时间一致，"
        "正反打遵守180度轴线 (same character, same outfit, same hairstyle, same location, "
        "same screen direction, prop continuity, gradual emotional continuity, obey 180-degree rule)"
    )
    CONTINUITY_NEGATIVE = (
        "(规避跨镜断裂：jump cut, time skip, sudden pose change, teleporting, changing background, "
        "changing outfit, changing hairstyle, changing face, inconsistent lighting, axis flip, "
        "broken eyeline, disappearing prop, duplicated prop, mismatched action, abrupt emotion change, "
        "random camera angle, spatial discontinuity, flickering, scene reset)"
    )
    # 承接上一镜的引导句 (用于第2镜起及分段视频后半段，实现动作匹配剪辑)
    CONTINUITY_CARRY = (
        "directly continues from the final frame of the previous shot, matching action and screen direction, "
        "承接上一镜最后一帧、动作与站位无缝衔接"
    )

    # 情绪与面部表情：正向微表情已由分镜文本承载，此处补防崩坏负面 (短剧情绪与面部表情提示词库.md §1/§8)
    EMOTION_FACE_NEGATIVE = (
        "(规避表情/面部崩坏：bad anatomy, distorted face, asymmetrical eyes, crossed eyes, extra teeth, "
        "deformed mouth, frozen face, plastic skin, uncanny smile, exaggerated expression, "
        "changing face, blurred facial features, extra fingers, extra hands, flickering)"
    )

    def generate_video(self, model: str, image_url: str, prompt: str, prefer_provider: str = None,
                       last_frame: str = None, ref_images: list = None,
                       ref_videos: list = None, ref_audios: list = None, duration: int = 5) -> str:
        """
        调用图生视频大模型 (Seedance 2.0 / Agnes)，支持：
          - 文生视频：image_url=None 且无参考素材
          - 图生视频-首帧：image_url=首帧图
          - 图生视频-首尾帧：image_url=首帧 + last_frame=尾帧
          - 多模态参考生视频：ref_images(0-9)/ref_videos(0-3)/ref_audios(0-3) + 可选 image_url
        降级机制(已移除所有「疑似真人」处理)：首帧/尾帧原样直接发送，Ark 首尾帧图生视频逻辑完整保留；
        Ark 失败(账号未授权/网络不可达)则静默降级给 Agnes 图生视频(接受真人脸)以维持首帧人物一致性，
        全部失败后再执行文生视频(不传首帧)作为终极兜底，确保每镜必出真实片且绝不刷屏报错。
        """
        prompt = self._enhancePromptWithRules(prompt)
        runtime = runtime_model_registry.resolve(model, "video")
        if runtime is None and not (model or "").strip():
            runtime = runtime_model_registry.first_for_category("video")
            if runtime:
                model = runtime.model_ids[0]

        # MiniMax H3 is a first-class video provider. It supports frame anchoring
        # (text / first / last / first+last) and Ref2VA mixed references. The
        # request is created and polled server-side so API keys never reach the UI.
        model_key = (model or "").lower().replace("_", "-")
        is_minimax = bool(runtime and runtime.provider == "minimax")
        if is_minimax or "minimax" in model_key or model_key in {"h3", "minimax-h3"}:
            try:
                from app.core.providers.minimax_h3 import MiniMaxH3Client
                from app.schema.production import H3VideoRequest

                h3_images = list(ref_images or [])
                h3_first = image_url
                h3_last = last_frame
                # Ref2VA video/audio and FL2VA anchors are distinct H3 modes.
                # When motion/audio references are supplied, preserve the image
                # as an ordinary subject/scene reference instead of claiming it
                # is an exact first-frame anchor.
                if h3_images or ref_videos or ref_audios:
                    if h3_first:
                        h3_images.insert(0, h3_first)
                    if h3_last:
                        h3_images.append(h3_last)
                    h3_first = None
                    h3_last = None
                request = H3VideoRequest(
                    model=model,
                    prompt=prompt,
                    first_frame=h3_first,
                    last_frame=h3_last,
                    reference_images=list(dict.fromkeys(h3_images))[:9],
                    reference_videos=list(dict.fromkeys(ref_videos or []))[:3],
                    reference_audios=list(dict.fromkeys(ref_audios or []))[:3],
                    duration_seconds=max(4, min(15, int(duration or 6))),
                    resolution=os.getenv("MINIMAX_H3_RESOLUTION", "1080p"),
                    aspect_ratio=os.getenv("MINIMAX_H3_ASPECT_RATIO", "9:16"),
                    native_audio=os.getenv("MINIMAX_H3_NATIVE_AUDIO", "1") not in {"0", "false", "False"},
                )
                endpoint = None
                runtime_key = None
                if runtime and runtime.provider == "minimax":
                    runtime_key = runtime.api_key
                    configured_base = runtime.base_url.rstrip("/")
                    endpoint = (
                        configured_base
                        if configured_base.endswith("/video_generation")
                        else configured_base + "/v2/video_generation"
                    )
                client = MiniMaxH3Client(api_key=runtime_key, endpoint=endpoint)
                try:
                    result = client.create_video(request)
                    if result.video_url:
                        return result.video_url
                    if result.task_id:
                        result = client.wait_for_video(
                            result.task_id,
                            timeout_seconds=float(os.getenv("MINIMAX_H3_WAIT_SECONDS", "900")),
                            poll_interval_seconds=float(os.getenv("MINIMAX_H3_POLL_SECONDS", "5")),
                        )
                        if result.video_url:
                            return result.video_url
                finally:
                    client.close()
                logger.warning("[ModelGateway] MiniMax H3 completed without a downloadable video URL; trying fallback")
            except Exception as exc:
                logger.warning(f"[ModelGateway] MiniMax H3 unavailable; trying configured fallback: {type(exc).__name__}")
        # 判定 Seedance 2.0 任务模式 (用于提示词优化器的模式提示)
        if last_frame:
            mode = "first_last_frame"
        elif ref_images or ref_videos or ref_audios:
            mode = "multi_ref"
        elif image_url:
            mode = "first_frame"
        else:
            mode = "text_to_video"

        primary = self._detect_provider(model, default="seedance")
        # 降级队列：文生图同源优先，依次尝试，避免重复
        order = []
        runtime_provider = runtime.provider if runtime else None
        for p in [prefer_provider, runtime_provider, "seedance", primary, "agnes"]:
            if p and p in ("seedance", "agnes") and p not in order:
                order.append(p)

        opt_prompt = None

        # 1. 图生视频(保留首帧/尾帧人物一致性)：按降级队列 (默认 seedance(Ark) 优先 -> agnes) 依次尝试。
        #    已彻底【移除所有「疑似真人」处理】：首帧/尾帧/参考图一律原样直接发送 ——
        #    不再做 volces.com 自产白名单门控、不再做 DEID 去脸构图、不再过滤授权脸、
        #    不再有 __ARK_SENSITIVE__ 哨兵与「首帧仍被判疑似真人」降级刷屏。
        #    Ark 首尾帧图生视频逻辑【完整保留】；若 Ark 因账号未授权/网络不可达而失败，
        #    会静默返回 None 并无缝落到 Agnes(接受任意写实人脸首帧) 继续图生视频，绝不刷屏报错。
        for name in order:
            if runtime and name == runtime.provider:
                key, b_url, video_model = runtime.api_key, runtime.base_url, model
            else:
                key, b_url, _ = self._provider_creds(name)
                video_model = self.seedance_model_name
            if not self._is_valid_key(key):
                continue

            if name == "seedance":
                if opt_prompt is None:
                    opt_prompt = self.optimize_video_prompt(prompt, mode=mode)
                # 火山 Ark 首帧/尾帧/多模态参考 图生视频：原样上传，不做任何疑似真人预处理
                url = self._ark_video(key, b_url, opt_prompt,
                                      first_frame=image_url, last_frame=last_frame,
                                      ref_images=ref_images, ref_videos=ref_videos, ref_audios=ref_audios,
                                      duration=duration, model_name=video_model)
                if url:
                    logger.info(f"[ModelGateway] Seedance 图生视频成功 (mode={mode}): {url[:60]}...")
                    return url

            elif name == "agnes":
                # Agnes 接收任意写实人脸首帧，无真人风控；发送清洗后的干净写实提示词。
                url = self._agnes_video(key, b_url, image_url, self._sanitize_prompt_for_agnes(opt_prompt or prompt))
                if url:
                    logger.info(f"[ModelGateway] Agnes 图生视频成功 (mode={mode}): {url[:60]}...")
                    return url

        # 2. 终极兜底：带首帧图生视频均不可用时，降级为文生视频(不传首帧，必出片)。
        logger.info("[ModelGateway] 带首帧图生视频暂不可用，降级为文生视频兜底")
        for name in order:
            if runtime and name == runtime.provider:
                key, b_url, video_model = runtime.api_key, runtime.base_url, model
            else:
                key, b_url, _ = self._provider_creds(name)
                video_model = self.seedance_model_name
            if not self._is_valid_key(key):
                continue
            if name == "seedance":
                if opt_prompt is None:
                    opt_prompt = self.optimize_video_prompt(prompt, mode=mode)
                url = self._ark_video(
                    key,
                    b_url,
                    opt_prompt,
                    first_frame=None,
                    duration=duration,
                    model_name=video_model,
                )
                if url:
                    logger.info(f"[ModelGateway] Seedance 文生视频兜底成功: {url[:60]}...")
                    return url
            elif name == "agnes":
                # Ark 不可达或失败时，Agnes 文生视频(不传首帧)兜底，确保每镜必出真实片。
                url = self._agnes_video(key, b_url, None, self._sanitize_prompt_for_agnes(opt_prompt or prompt))
                if url:
                    logger.info(f"[ModelGateway] Agnes 文生视频兜底成功: {url[:60]}...")
                    return url

        # 所有在线视频 provider 均不可用：返回 None，让上层跳过该镜 (Fail loud)，不混入占位视频。
        logger.error("[ModelGateway] 所有在线视频 provider 均不可用 (Seedance/Agnes)，本镜无真实视频产出")
        return None

    def generate_tts(self, model: str, voice_role: str, text: str):
        """
        AI 配音兜底接口。真实逐镜/全局配音由 media_compositor.synthesize_dialogue_track 生成，
        此处不再返回任何硬编码占位 mp3。无可用配音时返回 None，由上层据实标记"占位音频"。
        """
        return None

    def get_genre(self, title: str) -> str:
        """
        基于短剧题材类型总结文档规则，匹配选题题材
        """
        t = title.lower()
        rules = {
            "overseas_us": ["狼人", "吸血鬼", "mafia", "黑帮", "alpha", "omega", "亿万富翁", "欧美", "wolf", "vampire", "lucas", "elena"],
            "overseas_other": ["东南亚", "中东", "拉美", "酋长", "沙漠", "异域", "王子", "物理", "楚云溪", "哈曼"],
            "interactive": ["互动", "投票", "多结局", "沉浸式", "选项", "刺客", "抉择"],
            "military": ["军事", "特种兵", "谍战", "卧底", "特工", "维和", "战火", "毒枭", "战风", "卡洛斯"],
            "sports": ["体育", "竞技", "电竞", "格斗", "赛车", "篮球", "足球", "铁拳", "八角笼", "毁灭者"],
            "food": ["美食", "深夜食堂", "治愈", "厨师", "小店", "菜肴", "长寿面", "面条", "食客"],
            "horror": ["恐怖", "灵异", "怪谈", "鬼", "诡异", "老宅", "禁忌", "邪祟", "纸人", "扎纸", "林九"],
            "xianxia": ["修真", "仙侠", "飞升", "魔尊", "仙女", "废材修仙", "洞府", "渡劫", "萧凡", "仙门", "清虚"],
            "wuxia": ["武侠", "江湖", "剑侠", "剑客", "剑意", "决战", "门派", "武林", "退隐", "剑", "侠", "夜归人"],
            "palace_intrigue": ["宫斗", "权谋", "帝王", "夺嫡", "冷宫", "妃子", "权臣", "太子", "古装", "甄姬", "贵妃"],
            "time_travel": ["穿越", "穿书", "快穿", "系统", "签到", "系统流", "觉醒", "攻略", "皇后", "女配", "云舒"],
            "mystery": ["悬疑", "推理", "密室", "连环杀人", "心理", "人格", "催眠", "反转", "凶手", "绑架", "失踪", "冤案", "侦探", "法医", "张警官"],
            "male_counterattack": ["赘婿", "战神", "神医", "龙王", "兵王", "下山", "归来", "回城", "大佬", "扮猪吃虎", "首富", "叶凡"],
            "family": ["婆媳", "出轨", "全职妈妈", "离婚", "育儿", "家暴", "家庭", "小三", "沈秋月"],
            "campus": ["校园", "暗恋", "学霸", "学渣", "校花", "校草", "青梅竹马", "同桌", "毕业", "陆星野", "林溪"],
            "rebirth_revenge": ["重生", "复仇", "逆袭", "打脸", "渣男", "渣女", "改命", "前世", "当年", "代价", "报仇", "顾渊", "林雪"],
            "romance": ["霸总", "总裁", "千金", "契约", "闪婚", "豪门", "甜宠", "虐恋", "替身", "白月光", "金主", "恋爱", "追妻", "追爱", "顾安然", "陆霆骁"],
            "car": ["车", "车载", "配件", "极客", "座舱", "车王", "方舟"],
            "sci_fi": ["科幻", "末日", "废土", "荒岛", "太空", "全息", "AI", "智能", "平行时空", "外星人", "超能力", "仿生人", "零号"],
            "comedy": ["喜剧", "搞笑", "幽默", "沙雕", "无厘头", "整蛊", "爆笑", "反差", "互换"],
            "retro_romance": ["年代", "知青", "怀旧", "军婚", "90年代", "风口", "创业", "九零", "周向东", "苏曼"],
            "urban_realism": ["律师", "庭审", "辩护", "法庭", "律政", "被告", "高公子", "陆律师", "商战", "大少"]
        }
        for g_name, keywords in rules.items():
            if any(kw in t for kw in keywords):
                return g_name
        return "general"
