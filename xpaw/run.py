# coding=utf-8

import logging
import os
from os.path import join, isfile
import sys
import signal

from tornado.ioloop import IOLoop

from .config import BaseConfig, Config
from .cluster import LocalCluster
from .utils import configure_logger, configure_tornado_logger, daemonize, load_config, iter_settings
from .spider import RequestsSpider

log = logging.getLogger(__name__)


def run_crawler(proj_dir, **kwargs):
    config = BaseConfig(kwargs)
    run_cluster(proj_dir=proj_dir, config=config)


def run_spider(spider, **kwargs):
    config = BaseConfig(kwargs)
    config['spider'] = spider
    run_cluster(config=config)


def run_cluster(proj_dir=None, config=None):
    proj_config = load_project_config(proj_dir)
    proj_config.update(config)
    config = proj_config

    logger = configure_logger('xpaw', config)
    configure_tornado_logger(logger.handlers)
    if config.getbool('daemon'):
        daemonize()
    pid_file = config.get('pid_file')
    _write_pid_file(pid_file)
    try:
        cluster = LocalCluster(config)
    except Exception:
        log.error('Failed to create cluster', exc_info=True)
        _remove_pid_file(pid_file)
        raise
    default_signal_handlers = _set_signal_handlers(cluster)
    try:
        IOLoop.current().run_sync(cluster.run)
    finally:
        _remove_pid_file(pid_file)
        _recover_signal_handlers(default_signal_handlers)


def make_requests(requests, **kwargs):
    if 'log_level' not in kwargs:
        kwargs['log_level'] = 'WARNING'
    start_requests = [r for r in requests]
    results = [None] * len(start_requests)
    run_spider(RequestsSpider, start_requests=start_requests, results=results, **kwargs)
    return results


def load_project_config(proj_dir):
    if proj_dir is not None and proj_dir not in sys.path:
        # add project path
        sys.path.append(proj_dir)
    config = Config()
    if proj_dir is not None:
        config_file = join(proj_dir, 'config.py')
        if isfile(config_file):
            c = load_config(config_file)
            for k, v in iter_settings(c):
                config[k] = v
    return config


def _write_pid_file(pid_file):
    if pid_file is not None:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))


def _remove_pid_file(pid_file):
    if pid_file is not None:
        try:
            os.remove(pid_file)
        except Exception as e:
            log.warning('Cannot remove PID file %s: %s', pid_file, e)


def _set_signal_handlers(cluster):
    def _exit(signum, frame):
        log.info('Received exit signal: %s', signum)
        IOLoop.current().add_callback(cluster.stop)

    default_signal_handlers = [(signal.SIGINT, signal.getsignal(signal.SIGINT)),
                               (signal.SIGTERM, signal.getsignal(signal.SIGTERM))]
    signal.signal(signal.SIGINT, _exit)
    signal.signal(signal.SIGTERM, _exit)
    return default_signal_handlers


def _recover_signal_handlers(handlers):
    for h in handlers:
        signal.signal(h[0], h[1])
