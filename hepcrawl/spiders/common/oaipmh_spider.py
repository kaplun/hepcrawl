# -*- coding: utf-8 -*-
#
# This file is part of hepcrawl.
# Copyright (C) 2017 CERN.
#
# hepcrawl is a free software; you can redistribute it and/or modify it
# under the terms of the Revised BSD License; see LICENSE file for
# more details.

"""Generic spider for OAI-PMH servers."""

import abc
import logging
from errno import EEXIST as FILE_EXISTS, ENOENT as NO_SUCH_FILE_OR_DIR
from datetime import datetime
from dateutil import parser as dateparser
import hashlib
import json
from os import path, makedirs

from sickle import Sickle
from sickle.oaiexceptions import NoRecordsMatch

from scrapy.http import Request, XmlResponse
from scrapy.selector import Selector
from .stateful_spider import StatefulSpider


LOGGER = logging.getLogger(__name__)


class NoLastRunToLoad(Exception):
    """Error raised when there was a problem with loading the last_runs file"""
    def __init__(self, file_path):
        self.message = "Failed to load file at {}".format(file_path)


class OAIPMHSpider(StatefulSpider):
    """
    Implements a spider for the OAI-PMH protocol by using the Python sickle library.

    In case of successful harvest (OAI-PMH crawling) the spider will remember
    the initial starting date and will use it as `from_date` argument on the
    next harvest.
    """
    __metaclass__ = abc.ABCMeta
    name = 'OAI-PMH'

    def __init__(
        self,
        url,
        metadata_prefix='oai_dc',
        oai_set=None,
        alias=None,
        from_date=None,
        until_date=None,
        *args, **kwargs
    ):
        super(OAIPMHSpider, self).__init__(*args, **kwargs)
        self.url = url
        self.metadata_prefix = metadata_prefix
        self.set = oai_set
        self.from_date = from_date
        self.until_date = until_date

    def start_requests(self):
        self.from_date = self.from_date or self._resume_from
        started_at = datetime.utcnow()

        LOGGER.info("Starting harvesting of {url} with set={set} and "
                    "metadataPrefix={metadata_prefix}, from={from_date}, "
                    "until={until_date}".format(
            url=self.url,
            set=self.set,
            metadata_prefix=self.metadata_prefix,
            from_date=self.from_date,
            until_date=self.until_date
        ))

        request = Request('oaipmh+{}'.format(self.url), self.parse)
        yield request

        now = datetime.utcnow()
        self._save_run(started_at)

        LOGGER.info("Harvesting completed. Next harvesting will resume from {}"
                    .format(self.until_date or now.strftime('%Y-%m-%d')))

    @abc.abstractmethod
    def parse_record(self, record):
        """
        This method need to be reimplemented in order to provide special parsing.

        Args:
            record (scrapy.selector.Selector): selector on the parsed record
        """
        raise NotImplementedError()

    def parse(self, response):
        sickle = Sickle(self.url)
        try:
            records = sickle.ListRecords(**{
                'metadataPrefix': self.metadata_prefix,
                'set': self.set,
                'from': self.from_date,
                'until': self.until_date,
            })
        except NoRecordsMatch as err:
            LOGGER.warning(err)
            raise StopIteration()
        for record in records:
            response = XmlResponse(self.url, encoding='utf-8', body=record.raw)
            selector = Selector(response, type='xml')
            yield self.parse_record(selector)

    def _make_alias(self):
        return 'metadataPrefix={metadata_prefix}&set={set}'.format(
            metadata_prefix=self.metadata_prefix,
            set=self.set
        )

    def _last_run_file_path(self):
        """Render a path to a file where last run information is stored.

        Returns:
            string: path to last runs path
        """
        lasts_run_path = self.settings['LAST_RUNS_PATH']
        file_name = hashlib.sha1(self._make_alias()).hexdigest() + '.json'
        return path.join(lasts_run_path, self.name, file_name)

    def _load_last_run(self):
        """Return stored last run information

        Returns:
            Optional[dict]: last run information or None if don't exist
        """
        file_path = self._last_run_file_path()
        try:
            with open(file_path) as f:
                last_run = json.load(f)
                LOGGER.info('Last run file loaded: {}'.format(repr(last_run)))
                return last_run
        except IOError as exc:
            if exc.errno == NO_SUCH_FILE_OR_DIR:
                raise NoLastRunToLoad(file_path)
            raise

    def _save_run(self, started_at):
        """Store last run information

        Args:
            started_at (datetime.datetime)

        Raises:
            IOError: if writing the file is unsuccessful
        """
        last_run_info = {
            'spider': self.name,
            'url': self.url,
            'metadata_prefix': self.metadata_prefix,
            'set': self.set,
            'from_date': self.from_date,
            'until_date': self.until_date,
            'last_run_started_at': started_at.isoformat(),
            'last_run_finished_at': datetime.utcnow().isoformat(),
        }
        file_path = self._last_run_file_path()
        LOGGER.info("Last run file saved to {}".format(file_path))
        try:
            makedirs(path.dirname(file_path))
        except OSError as exc:
            if exc.errno != FILE_EXISTS:
                raise
        with open(file_path, 'w') as f:
            json.dump(last_run_info, f, indent=4)

    @property
    def _resume_from(self):
        try:
            last_run = self._load_last_run()
            resume_at = last_run['until_date'] or last_run['last_run_finished_at']
            date_parsed = dateparser.parse(resume_at)
            return date_parsed.strftime('%Y-%m-%d')
        except NoLastRunToLoad:
            return None