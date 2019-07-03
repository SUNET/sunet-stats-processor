from __future__ import annotations

import logging
import logging.config
import os
import sys
from dataclasses import dataclass, replace
from os import environ
from typing import Mapping, Type, Union, List, Dict

import falcon
import yaml
import requests
from falcon import Request, Response

__author__ = 'ft'


@dataclass
class ParsedLine(object):
    name: bytes
    value: Union[int, float]
    ts: bytes

    @classmethod
    def from_bytes(cls: Type[ParsedLine], data) -> ParsedLine:
        """
        Parse an influxdb line protocol line.

        Example:
            b'test.counter,host=foo,metric_type=counter value=103964i 1562141920000000000'
        """
        (name, full_value, ts) = data.split()
        if not full_value.startswith(b'value=') or b',' in full_value:
            raise ValueError('No field "value", or more fields than just "value="')
        rhs = full_value.split(b'=')[1]
        if rhs.endswith(b'i'):
            value = int(rhs[:-1])
        else:
            value = float(rhs[:-1])
        return cls(name + b',transform=delta', value, ts)

    def to_bytes(self):
        value = str(self.value).encode()
        if isinstance(self.value, int):
            value += b'i'
        return self.name + b' value=' + value + b' ' + self.ts

class Context(object):

    def __init__(self, config: Mapping):
        self.config = config
        self.history: Dict[bytes, ParsedLine] = {}
        self.max_age = int(self.config.get('MAX_AGE', os.environ.get('STATS_PROCESSOR_MAX_AGE', 21)))
        self.influx_url = config.get('INFLUX_URL', os.environ.get('STATS_PROCESSOR_INFLUX_URL',
                                                                  'http://localhost:8086/'))
        while self.influx_url.endswith('/'):
            self.influx_url = self.influx_url[:-1]

        if self.config.get('LOGGING'):
            logging.config.dictConfig(self.config.get('LOGGING'))
            self.logger = logging.getLogger('stats_processor')
        else:
            self.logger = logging.getLogger('stats_processor')
            sh = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(module)s - %(levelname)s - %(message)s')
            sh.setFormatter(formatter)
            self.logger.addHandler(sh)
            self.logger.setLevel(logging.DEBUG)


class LogRequests(object):

    def __init__(self, context: Context):
        self.context = context

    def process_request(self, req: Request, resp: Response):
        self.context.logger.debug(f'process_request: {req.method} {req.path}')


class BaseResource(object):

    def __init__(self, context: Context):
        self.context = context


class WriteResource(BaseResource):
    """
    Influxdb write operations
    """

    def on_post(self, req: Request, resp: Response):
        body = req.stream.read()
        self.context.logger.debug(f'Write endpoint input:\n{body}')
        res: List[bytes] = []
        counters: List[ParsedLine] = []
        # The sending Telegraf might buffer more than one value for a name, and they might arrive with oldest
        # data last, so first parse the whole body and put the counters in a list that we can sort on timestamp.
        for this in body.split(b'\n'):
            # Always preserve in original form
            res += [this]
            if b'metric_type=counter' in this:
                try:
                    parsed = ParsedLine.from_bytes(this)
                    self.context.logger.debug(parsed)
                    counters += [parsed]
                except ValueError:
                    self.context.logger.warning(f'Failed to parse {repr(this)}')
                    pass

        # sort based on timestamp if telegraf sends us more than one value at once
        for this in sorted(counters, key=lambda x: x.ts):
            self.context.logger.debug(f'Processing {this}')
            if this.name not in self.context.history:
                self.context.logger.info(f'Registering new counter: {this}')
                self.context.history[this.name] = this
                continue

            previous = self.context.history[this.name]
            age = self._calculate_age(this, previous)
            if age > self.context.max_age:
                self.context.logger.info(f'Previous value too old ({age} seconds), re-registering counter: {this}')
                self.context.history[this.name] = this
                continue

            if this.value < previous.value:
                self.context.logger.info(f'New value {this.value} is less than previous value {previous.value}, '
                                         f're-registering counter: {this}')
                self.context.history[this.name] = this
                continue

            delta = this.value - previous.value

            self.context.history[this.name] = this
            updated = replace(this, value=delta)
            output = updated.to_bytes()

            res += [output]

            self.context.logger.debug(f'Adding {output}')

        result = requests.post(f'{self.context.influx_url}{req.relative_uri}', data=b'\n'.join(res))
        self.context.logger.debug(f'Proxy "write" result: {result} {result.text}')
        resp.status = f'{result.status_code} {result.reason}'

    def _calculate_age(self, this: ParsedLine, previous: ParsedLine) -> float:
        """
        Return the difference (in seconds) between the timestamps of two influxdb lines.

        Note: influxdb uses nanoseconds resolution, so divide it back to seconds.
        """
        t1 = int(previous.ts)
        t2 = int(this.ts)
        return (t2 - t1) / 10 ** 9


class QueryResource(BaseResource):
    """ Telegraf create database on startup """

    def on_post(self, req: Request, resp: Response):
        body = req.stream.read()
        self.context.logger.debug(f'Query endpoint input:\n{body}')

        result = requests.post(f'{self.context.influx_url}{req.relative_uri}', data=body,
                               headers={'content-type': req.content_type})
        self.context.logger.debug(f'Proxy "query" result: {result} {result.text}')
        resp.status = f'{result.status_code} {result.reason}'

# Read config
config_path = environ.get('STATS_PROCESSOR_CONFIG')
config = dict()
if config_path:
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

context = Context(config)
context.logger.info('Starting app')

api = falcon.API(middleware=LogRequests(context))

api.add_route('/write', WriteResource(context=context))
api.add_route('/query', QueryResource(context=context))

context.logger.info(f'app running (forwarding to influxdb at {context.influx_url}...')
