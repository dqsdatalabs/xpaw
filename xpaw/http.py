# coding=utf-8

import re
import cgi

from tornado.httputil import HTTPHeaders as HttpHeaders


class HttpRequest:
    def __init__(self, url, method="GET", body=None, params=None, headers=None, proxy=None,
                 timeout=20, verify_ssl=False, allow_redirects=True, auth=None, proxy_auth=None,
                 priority=None, dont_filter=False, callback=None, errback=None, meta=None):
        """
        Construct an HTTP request.
        """
        self.url = url
        self.method = method
        self.body = body
        self.params = params
        self.headers = headers or {}
        self.proxy = proxy
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.allow_redirects = allow_redirects
        self.auth = auth
        self.proxy_auth = proxy_auth
        self.priority = priority
        self.dont_filter = dont_filter
        self.callback = callback
        self.errback = errback
        self._meta = dict(meta) if meta else {}

    def __str__(self):
        return '<{}, {}>'.format(self.method, self.url)

    __repr__ = __str__

    @property
    def meta(self):
        return self._meta

    def copy(self):
        return self.replace()

    def replace(self, **kwargs):
        for i in ["url", "method", "body", "params", "headers", "proxy",
                  "timeout", "verify_ssl", "allow_redirects", "auth", "proxy_auth",
                  "priority", "dont_filter", "callback", "errback", "meta"]:
            kwargs.setdefault(i, getattr(self, i))
        return type(self)(**kwargs)


class HttpResponse:
    def __init__(self, url, status, body=None, headers=None,
                 request=None):
        """
        Construct an HTTP response.
        """
        self.url = url
        self.status = int(status)
        self.body = body
        self.headers = headers or {}
        self.request = request

    def __str__(self):
        return '<{}, {}>'.format(self.status, self.url)

    __repr__ = __str__

    @property
    def encoding(self):
        if hasattr(self, "_encoding"):
            return self._encoding
        encoding = get_encoding_from_header(self.headers.get("Content-Type"))
        if not encoding and self.body:
            encoding = get_encoding_from_content(self.body)
        self._encoding = encoding or "utf-8"
        return self._encoding

    @encoding.setter
    def encoding(self, value):
        self._encoding = value

    @property
    def text(self):
        if hasattr(self, "_text") and self._text:
            return self._text
        if not self.body:
            return ""
        self._text = self.body.decode(self.encoding, errors="replace")
        return self._text

    @property
    def meta(self):
        if self.request:
            return self.request.meta

    def copy(self):
        return self.replace()

    def replace(self, **kwargs):
        for i in ["url", "status", "body", "headers", "request"]:
            kwargs.setdefault(i, getattr(self, i))
        return type(self)(**kwargs)


def get_encoding_from_header(content_type):
    if content_type:
        content_type, params = cgi.parse_header(content_type)
        if "charset" in params:
            return params["charset"]


_charset_flag = re.compile(r"""<meta.*?charset=["']*(.+?)["'>]""", flags=re.I)
_pragma_flag = re.compile(r"""<meta.*?content=["']*;?charset=(.+?)["'>]""", flags=re.I)
_xml_flag = re.compile(r"""^<\?xml.*?encoding=["']*(.+?)["'>]""")


def get_encoding_from_content(content):
    if isinstance(content, bytes):
        content = content.decode("ascii", errors="ignore")
    elif not isinstance(content, str):
        raise ValueError("content should be bytes or str")
    s = _charset_flag.search(content)
    if s:
        return s.group(1).strip()
    s = _pragma_flag.search(content)
    if s:
        return s.group(1).strip()
    s = _xml_flag.search(content)
    if s:
        return s.group(1).strip()
