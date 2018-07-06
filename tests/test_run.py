# coding=utf-8

from os.path import join, exists
import asyncio
from urllib.parse import urljoin
import os
import signal
import time
from threading import Thread

from xpaw.cli import main
from xpaw.run import run_crawler
from xpaw.spider import Spider
from xpaw.http import HttpRequest
from xpaw.selector import Selector
from xpaw.run import run_spider
from xpaw.item import Item, Field
from xpaw.errors import IgnoreItem
from xpaw.queue import PriorityQueue


def test_run_crawler(tmpdir, capsys):
    proj_name = 'test_run_crawler'
    proj_dir = join(str(tmpdir), proj_name)
    main(argv=['xpaw', 'init', proj_dir])
    run_crawler(proj_dir, downloader_timeout=0.01, log_level='WARNING')
    _, _ = capsys.readouterr()


class DummySpider(Spider):
    async def start_requests(self):
        await asyncio.sleep(0.2, loop=self.cluster.loop)

    def parse(self, response):
        pass


def test_run_spider():
    run_spider(DummySpider, downloader_timeout=0.1)


class FooSpider(Spider):
    def start_requests(self):
        yield HttpRequest('http://httpbin.org/get')

    async def parse(self, response):
        pass


class BadQueue(PriorityQueue):
    def __init__(self, loop=None, **kwargs):
        super().__init__(loop=loop, **kwargs)
        self.loop = loop

    async def pop(self):
        await super().pop()
        raise RuntimeError('not an error actually')


class BadQueue2(PriorityQueue):
    async def pop(self):
        raise RuntimeError('not an error actually')


def test_coro_terminated():
    run_spider(FooSpider, downloader_clients=2, queue=BadQueue, max_retry_times=0, downloader_timeout=0.1)


def test_coro_terminated2():
    run_spider(FooSpider, downloader_clients=2, queue=BadQueue2, max_retry_times=0, downloader_timeout=0.1)


class LinkItem(Item):
    url = Field()


class LinkPipeline:
    def __init__(self, n, data, cluster):
        self.n = n
        self.data = data
        self.cluster = cluster

    @classmethod
    def from_cluster(cls, cluster):
        n = cluster.config.getint('link_count')
        data = cluster.config.get('link_data')
        return cls(n, data, cluster)

    async def handle_item(self, item):
        url = item['url']
        if url == "http://httpbin.org/links/{}".format(self.n):
            raise IgnoreItem
        self.data.add(url)


class MyError(Exception):
    pass


class LinkDownloaderMiddleware:
    def handle_request(self, request):
        if request.url == 'http://httpbin.org/status/406':
            return HttpRequest('http://httpbin.org/status/407')
        if request.url == 'http://httpbin.org/status/410':
            raise MyError

    def handle_response(self, request, response):
        if request.url == 'http://httpbin.org/status/407':
            return HttpRequest('http://httpbin.org/status/409')

    def handle_error(self, request, error):
        if isinstance(error, MyError):
            return HttpRequest('http://httpbin.org/status/411')


class LinkSpiderMiddleware:
    def handle_input(self, response):
        if response.request.url == 'http://httpbin.org/status/412':
            raise MyError

    def handle_output(self, response, result):
        return result

    def handle_error(self, response, error):
        if isinstance(error, MyError):
            return ()


class LinkSpider(Spider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.link_count = self.config.get('link_count')
        self.data = self.config.get('link_data')

    def start_requests(self):
        yield HttpRequest("http://localhost:80", errback=self.error_back)
        yield HttpRequest("http://localhost:81", errback=self.async_error_back)
        yield HttpRequest("http://httpbin.org/status/451", callback=self.generator_parse)
        yield HttpRequest("http://httpbin.org/status/452", callback=self.func_prase)
        yield HttpRequest("http://httpbin.org/status/453", callback=self.async_parse)
        yield HttpRequest("http://httpbin.org/status/454", callback=self.return_list_parse)
        yield HttpRequest("http://httpbin.org/status/455", callback=self.return_none)
        yield HttpRequest("http://httpbin.org/status/456", errback=self.handle_input_error)
        yield HttpRequest("http://httpbin.org/status/408")
        yield HttpRequest("http://httpbin.org/links/{}".format(self.link_count))

    def parse(self, response):
        selector = Selector(response.text)
        for href in selector.xpath('//a/@href').text:
            yield HttpRequest(urljoin(str(response.url), href))
        yield LinkItem(url=response.request.url)

    def error_back(self, request, err):
        self.data.add(request.url)
        raise RuntimeError('not an error actually')

    async def async_error_back(self, request, err):
        self.data.add(request.url)
        raise RuntimeError('not an error actually')

    def generator_parse(self, response):
        self.data.add(response.request.url)
        if response.status / 100 != 2:
            raise RuntimeError('not an error actually')
        # it will never come here
        yield None

    def func_prase(self, response):
        self.data.add(response.request.url)
        raise RuntimeError('not an error actually')

    async def async_parse(self, response):
        self.data.add(response.request.url)
        raise RuntimeError('not an error actually')

    def return_list_parse(self, response):
        self.data.add(response.request.url)
        return []

    def return_none(self, response):
        self.data.add(response.request.url)

    def handle_input_error(self, request, error):
        assert isinstance(error, MyError)
        self.data.add(request.url)


def test_spider_handlers():
    link_data = set()
    link_count = 3
    link_total = 11
    run_spider(LinkSpider, downloader_timeout=60, log_level='INFO', item_pipelines=[LinkPipeline],
               link_data=link_data, link_count=link_count,
               downloader_clients=2, spider_middlewares=[LinkSpiderMiddleware],
               downloader_middlewares=[LinkDownloaderMiddleware])
    assert len(link_data) == link_total
    for i in range(link_count):
        assert "http://httpbin.org/links/{}/{}".format(link_count, i) in link_data
    assert "http://localhost:80" in link_data
    assert "http://localhost:81" in link_data
    assert "http://httpbin.org/status/451" in link_data
    assert "http://httpbin.org/status/452" in link_data
    assert "http://httpbin.org/status/453" in link_data
    assert "http://httpbin.org/status/454" in link_data
    assert "http://httpbin.org/status/455" in link_data
    assert "http://httpbin.org/status/456" in link_data


class WaitSpider(Spider):
    def start_requests(self):
        yield HttpRequest('http://httpbin.org/get')

    async def parse(self, response):
        while True:
            await asyncio.sleep(5, loop=self.cluster.loop)


def check_pid(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


class ExceptionThread(Thread):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bucket = []

    def run(self):
        try:
            super().run()
        except Exception as e:
            self.bucket.append(e)
            raise


def test_kill_spider(tmpdir):
    pid_file = join(str(tmpdir), 'pid')
    log_file = join(str(tmpdir), 'log')
    t = ExceptionThread(target=_check_thread, args=(pid_file,))
    t.start()
    run_spider(WaitSpider, pid_file=pid_file, log_file=log_file)
    t.join()
    assert len(t.bucket) == 0, 'Exception in thread'


def _check_thread(pid_file):
    t = 10
    while t > 0 and not exists(pid_file):
        t -= 1
        time.sleep(1)
    assert t > 0
    with open(pid_file, 'rb') as f:
        pid = int(f.read().decode())
    assert check_pid(pid) is True
    os.kill(pid, signal.SIGTERM)
    t = 10
    while t > 0 and exists(pid_file):
        t -= 1
        time.sleep(1)
    assert t > 0
