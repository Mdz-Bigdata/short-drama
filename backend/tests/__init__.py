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
# 跨集场记的回查同理：一次额外的模型调用，测试里默认关，test_story_state 自己打开。
os.environ.setdefault("SCREENWRITING_STATE_CHECK", "0")
# 一集短片的场记自查同理：test_script_self_check 自己打开。
os.environ.setdefault("SCREENWRITING_SELF_CHECK", "0")
# 第 2 阶段大纲先行、详细剧本转后台线程撰写：测试默认整段写完，专门测它的用例自己打开。
os.environ.setdefault("SCRIPT_OUTLINE_FIRST", "0")
# 打戏片段出来后抽帧问看图模型、不合格重出：测试默认关掉，专门测它的用例自己打开。
os.environ.setdefault("FIGHT_CLIP_CHECK", "0")
# 片段下载失败后的重试间隔：测试里的链接都是假的，等也等不来。
os.environ.setdefault("MEDIA_DOWNLOAD_RETRY_SECONDS", "0")
# 阶段 Agent 的自进化会在后台线程里把同一次调用再跑几遍并写经验库：测试默认关掉(后台线程会活过替身的作用域，
# 还会写进真实的 learned/harness_library)，专门测它的用例自己打开并把经验库指到临时目录。
os.environ.setdefault("HARNESS_EVOLUTION", "off")

# 兜底：上面的开关只管已知的几处，新加的一步忘了替换网关时，测试也不能真连供应商(花钱，还可能一直卡着)。
# 真实网络请求一律当断网处理，抛各库自己的连接错误；本机和 TestClient 不受影响。真要连网的手动测试设 TESTS_ALLOW_NETWORK=1。
if os.environ.get("TESTS_ALLOW_NETWORK") != "1":
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    import dotenv
    import httpx
    import requests.adapters

    # 网关和 main.py 每次都会 load_dotenv()：测试从 backend/ 跑，会把本机 .env 里真实的供应商密钥读进来。
    # 测试不读 .env，要密钥的用例自己 patch 环境变量。
    dotenv.load_dotenv = lambda *args, **kwargs: False

    _LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}

    def _offline(url: object) -> str | None:
        host = urlsplit(str(url)).hostname or ""
        return None if host in _LOCAL_HOSTS else f"tests are offline: blocked a real request to {host}"

    _requests_send = requests.adapters.HTTPAdapter.send

    def _requests_offline(self, request, *args, **kwargs):
        refused = _offline(request.url)
        if refused:
            raise requests.exceptions.ConnectionError(refused, request=request)
        return _requests_send(self, request, *args, **kwargs)

    _httpx_send = httpx.HTTPTransport.handle_request
    _httpx_async_send = httpx.AsyncHTTPTransport.handle_async_request

    def _httpx_offline(self, request):
        refused = _offline(request.url)
        if refused:
            raise httpx.ConnectError(refused, request=request)
        return _httpx_send(self, request)

    async def _httpx_async_offline(self, request):
        refused = _offline(request.url)
        if refused:
            raise httpx.ConnectError(refused, request=request)
        return await _httpx_async_send(self, request)

    # 查域名也算连网(下载前要确认不是内网地址)：假域名不去问真实的 DNS。
    _getaddrinfo = socket.getaddrinfo

    def _is_address(host) -> bool:
        try:
            ipaddress.ip_address(str(host))
            return True
        except ValueError:
            return False

    def _getaddrinfo_offline(host, *args, **kwargs):
        # 不带主机名(绑定端口)和字面 IP 不查 DNS，照常。
        if host and not _is_address(host) and _offline(f"//{host}"):
            raise socket.gaierror(socket.EAI_NONAME, f"tests are offline: no DNS lookup for {host}")
        return _getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = _getaddrinfo_offline
    requests.adapters.HTTPAdapter.send = _requests_offline
    httpx.HTTPTransport.handle_request = _httpx_offline
    httpx.AsyncHTTPTransport.handle_async_request = _httpx_async_offline

# unittest 的异步用例(IsolatedAsyncioTestCase)写死开 asyncio 调试模式：每个 future 和回调都抓一次调用栈，
# 财务这几组测试一大半时间耗在这里。默认关掉；要查没 await 的协程、慢回调时设 TESTS_ASYNCIO_DEBUG=1。
if os.environ.get("TESTS_ASYNCIO_DEBUG") != "1":
    import unittest

    _setup_runner = getattr(unittest.IsolatedAsyncioTestCase, "_setupAsyncioRunner", None)
    if _setup_runner is not None:
        def _setup_quiet_runner(self):
            _setup_runner(self)
            runner = getattr(self, "_asyncioRunner", None)
            if runner is not None:
                runner.get_loop().set_debug(False)

        unittest.IsolatedAsyncioTestCase._setupAsyncioRunner = _setup_quiet_runner
