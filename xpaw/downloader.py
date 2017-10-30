# coding=utf-8

import logging
import asyncio
import inspect

import aiohttp

from xpaw.middleware import MiddlewareManager
from xpaw.http import HttpRequest, HttpResponse
from xpaw.errors import NetworkError

log = logging.getLogger(__name__)


class Downloader:
    def __init__(self, timeout=None, verify_ssl=True, cookie_jar_enabled=False, loop=None):
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._loop = loop or asyncio.get_event_loop()
        if cookie_jar_enabled:
            self._cookie_jar = aiohttp.CookieJar(loop=self._loop)
        else:
            self._cookie_jar = None

    async def download(self, request):
        log.debug("HTTP request: {} {}".format(request.method, request.url))
        timeout = request.meta.get("timeout")
        if not timeout:
            timeout = self._timeout
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=self._verify_ssl, loop=self._loop),
                                         cookies=request.cookies,
                                         cookie_jar=self._cookie_jar,
                                         loop=self._loop) as session:
            with aiohttp.Timeout(timeout, loop=self._loop):
                async with session.request(request.method,
                                           request.url,
                                           params=request.params,
                                           auth=request.auth,
                                           headers=request.headers,
                                           data=request.body,
                                           proxy=request.proxy,
                                           proxy_auth=request.proxy_auth) as resp:
                    body = await resp.read()
                    cookies = resp.cookies
        response = HttpResponse(resp.url,
                                resp.status,
                                headers=resp.headers,
                                body=body,
                                cookies=cookies)
        log.debug("HTTP response: {} {}".format(response.url, response.status))
        return response


class DownloaderMiddlewareManager(MiddlewareManager):
    def __init__(self, *middlewares):
        self._request_handlers = []
        self._response_handlers = []
        self._error_handlers = []
        super().__init__(*middlewares)

    def _add_middleware(self, middleware):
        super()._add_middleware(middleware)
        if hasattr(middleware, "handle_request"):
            self._request_handlers.append(middleware.handle_request)
        if hasattr(middleware, "handle_response"):
            self._response_handlers.insert(0, middleware.handle_response)
        if hasattr(middleware, "handle_error"):
            self._error_handlers.insert(0, middleware.handle_error)

    @classmethod
    def _middleware_list_from_cluster(cls, cluster):
        mw_list = cluster.config.get("downloader_middlewares")
        if mw_list:
            if not isinstance(mw_list, list):
                mw_list = [mw_list]
        else:
            mw_list = []
        log.info("Downloader middlewares: {}".format(mw_list))
        return mw_list

    async def download(self, downloader, request):
        try:
            res = await self._handle_request(request)
            if isinstance(res, HttpRequest):
                return res
            if res is None:
                try:
                    response = await downloader.download(request)
                except Exception as e:
                    log.debug("Network error, {}: {}".format(type(e).__name__, e))
                    raise NetworkError(e)
                else:
                    res = response
            _res = await self._handle_response(request, res)
            if _res:
                res = _res
        except Exception as e:
            res = await self._handle_error(request, e)
            if isinstance(res, Exception):
                raise res
            if res:
                return res
        else:
            return res

    async def _handle_request(self, request):
        for method in self._request_handlers:
            res = method(request)
            if inspect.iscoroutine(res):
                res = await res
            assert res is None or isinstance(res, (HttpRequest, HttpResponse)), \
                "Request handler must return None, HttpRequest or HttpResponse, got {}".format(type(res).__name__)
            if res:
                return res

    async def _handle_response(self, request, response):
        for method in self._response_handlers:
            res = method(request, response)
            if inspect.iscoroutine(res):
                res = await res
            assert res is None or isinstance(res, HttpRequest), \
                "Response handler must return None or HttpRequest, got {}".format(type(res).__name__)
            if res:
                return res

    async def _handle_error(self, request, error):
        for method in self._error_handlers:
            res = method(request, error)
            if inspect.iscoroutine(res):
                res = await res
            assert res is None or isinstance(res, (HttpRequest, HttpResponse)), \
                "Exception handler must return None, HttpRequest or HttpResponse, got {}".format(type(res).__name__)
            if res:
                return res
        return error
