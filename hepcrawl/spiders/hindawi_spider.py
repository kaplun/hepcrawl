# -*- coding: utf-8 -*-
#
# This file is part of hepcrawl.
# Copyright (C) 2016 CERN.
#
# hepcrawl is a free software; you can redistribute it and/or modify it
# under the terms of the Revised BSD License; see LICENSE file for
# more details.

"""Spider for Hindawi."""

from __future__ import absolute_import, print_function

import re

from scrapy import Request
from scrapy.spiders import XMLFeedSpider

from ..items import HEPRecord
from ..loaders import HEPLoader
from ..mappings import OA_LICENSES


class HindawiSpider(XMLFeedSpider):

    """Hindawi crawler

    OAI interface: http://www.hindawi.com/oai-pmh/
    Example:
    http://www.hindawi.com/oai-pmh/oai.aspx?verb=listrecords&set=HINDAWI.AA&metadataprefix=marc21&from=2015-01-01

    Sets to use:
    HINDAWI.AA (Advances in Astronomy)
    HINDAWI.AHEP (Advances in High Energy Physics)
    HINDAWI.AMP (Advances in Mathematical Physics)
    HINDAWI.JAS (Journal of Astrophysics)
    HINDAWI.JCMP (Journal of Computational Methods in Physics)
    HINDAWI.JGRAV (Journal of Gravity)

    Scrapes Hindawi metadata XML files one at a time.
    The actual files should be retrieved from Hindawi via its OAI interface.
    The file can contain multiple records.

    1. The spider will parse the local MARC21XML format file for record data

    2. Finally a HEPRecord will be created.


    Example usage:
    .. code-block:: console

        scrapy crawl hindawi -a source_file=file://`pwd`/tests/responses/hindawi/test_1.xml

    Happy crawling!
    """

    name = 'hindawi'
    start_urls = []
    iterator = 'xml'
    itertag = 'marc:record'

    namespaces = [
        ("OAI-PMH", "http://www.openarchives.org/OAI/2.0/"),
        ("marc", "http://www.loc.gov/MARC21/slim"),
        ("mml", "http://www.w3.org/1998/Math/MathML"),
    ]

    def __init__(self, source_file=None, *args, **kwargs):
        """Construct Hindawi spider."""
        super(HindawiSpider, self).__init__(*args, **kwargs)
        self.source_file = source_file

    def start_requests(self):
        """Default starting point for scraping shall be the local XML file."""
        yield Request(self.source_file)

    @staticmethod
    def get_affiliations(author):
        """Get the affiliations of an author."""
        affiliations_raw = author.xpath(
            "./subfield[@code='u']/text()").extract()
        affiliations = []
        for aff in affiliations_raw:
            affiliations.append(
                {"value": aff}
            )

        return affiliations

    def get_authors(self, node):
        """Gets the authors."""
        authors_first = node.xpath("./datafield[@tag='100']")
        authors_others = node.xpath("./datafield[@tag='700']")
        authors_raw = authors_first + authors_others
        authors = []
        for author in authors_raw:
            authors.append({
                'raw_name': author.xpath("./subfield[@code='a']/text()").extract_first(),
                'affiliations': self.get_affiliations(author)
            })

        return authors

    def get_urls_in_record(self, node):
        """Return all the different urls in the xml."""
        marc_856 = node.xpath(
            "./datafield[@tag='856']/subfield[@code='u']/text()").extract()
        marc_FFT = node.xpath(
            "./datafield[@tag='FFT']/subfield[@code='a']/text()").extract()
        all_links = list(set(marc_856 + marc_FFT))

        return self.differentiate_urls(all_links)

    @staticmethod
    def differentiate_urls(urls_in_record):
        """Determine what kind of urls the record has."""
        pdf_links = []
        xml_links = []
        splash_links = []
        for link in urls_in_record:
            if "pdf" in link.lower():
                pdf_links.append(link)
            elif "xml" in link.lower():
                xml_links.append(link)
            elif "dx.doi.org" in link.lower():
                splash_links.append(link)

        return (
            pdf_links,
            xml_links,
            splash_links,
        )

    @staticmethod
    def _get_license(node):
        """Get article licence."""
        # FIXME: do we need all this?
        openaccess = False
        licenses = {
            "CC-BY-3.0": {
                "title": "Creative Commons Attribution 3.0",
                "url": "http://creativecommons.org/licenses/by/3.0/"
            }
        }
        license_str = node.xpath(
            "./datafield[@tag='540']/subfield[@code='a']/text()").extract_first()
        license_url = node.xpath(
            "./datafield[@tag='540']/subfield[@code='u']/text()").extract_first()

        for lic in licenses:
            if license_str and license_str in lic or license_str in licenses[lic]["title"]:
                license_str = lic
                break

        for pattern in OA_LICENSES:
            if re.search(pattern, license_str):
                openaccess = True
                break

        return license_str, license_url, openaccess

    @staticmethod
    def get_copyright(node):
        """Get copyright year and statement."""
        copyright_raw = node.xpath(
            "./datafield[@tag='542']/subfield[@code='f']/text()").extract_first()
        cr_year = "".join(i for i in copyright_raw if i.isdigit())

        return copyright_raw, cr_year

    def create_fft_file(self, file_path, file_access, file_type):
        """Create a structured dictionary to add to 'files' item."""
        file_dict = {
            "access": file_access,
            "description": self.name.upper(),
            "url": file_path,
            "type": file_type,
        }
        return file_dict

    def parse_node(self, response, node):
        """Iterate all the record nodes in the XML and build the HEPRecord."""

        node.remove_namespaces()
        record = HEPLoader(item=HEPRecord(), selector=node, response=response)

        record.add_value('authors', self.get_authors(node))
        record.add_xpath('abstract', "./datafield[@tag='520']/subfield[@code='a']/text()")
        record.add_xpath('title',
                         "./datafield[@tag='245']/subfield[@code='a']/text()")
        record.add_xpath('date_published',
                         "./datafield[@tag='260']/subfield[@code='c']/text()")
        record.add_xpath('page_nr',
                         "./datafield[@tag='300']/subfield[@code='a']/text()")
        record.add_xpath('dois',
                         "./datafield[@tag='024'][subfield[@code='2'][contains(text(), 'DOI')]]/subfield[@code='a']/text()")
        record.add_xpath('journal_title',
                         "./datafield[@tag='773']/subfield[@code='p']/text()")
        record.add_xpath('journal_volume',
                         "./datafield[@tag='773']/subfield[@code='a']/text()")
        record.add_xpath('journal_year',
                         "./datafield[@tag='773']/subfield[@code='y']/text()")
        record.add_xpath('journal_issue',
                         "./datafield[@tag='773']/subfield[@code='n']/text()")
        record.add_xpath('journal_pages',
                         "./datafield[@tag='773']/subfield[@code='c']/text()")

        cr_statement, cr_year = self.get_copyright(node)
        record.add_value('copyright_statement', cr_statement)
        record.add_value('copyright_year', cr_year)

        pub_license, pub_license_url, openaccess = self._get_license(node)
        if pub_license:
            record.add_value('license', pub_license)
            record.add_value('license_url', pub_license_url)
            if openaccess:
                record.add_value('license_type', "open-access")

        pdf_links, xml_links, splash_links = self.get_urls_in_record(node)
        record.add_value('urls', splash_links)
        record.add_value('file_urls', pdf_links)
        if xml_links:
            record.add_value('additional_files',
                             [self.create_fft_file(xml,
                                                   "INSPIRE-HIDDEN",
                                                   "Fulltext") for xml in xml_links])
        record.add_value('collections', ['HEP', 'Citeable', 'Published'])
        record.add_xpath('source',
                         "./datafield[@tag='260']/subfield[@code='b']/text()")

        return record.load_item()
