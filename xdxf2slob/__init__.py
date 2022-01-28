# This file is part of Aard Dictionary Tools <http://aarddict.org>.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3
# as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License <http://www.gnu.org/licenses/gpl-3.0.txt>
# for more details.
#
# Copyright (C) 2008-2013  Igor Tkach

import argparse
import collections
import functools
import logging
import os
import sys
import urllib

from copy import deepcopy
from itertools import combinations
from xml.etree import ElementTree as etree

import slob

ARTICLE_CONTENT_TYPE = 'text/html;charset=utf-8'

ARTICLE_TEMPLATE = (
    '<script src="~/js/styleswitcher.js"></script>'
    '<link rel="stylesheet" href="~/css/default.css" type="text/css">'
    '<link rel="alternate stylesheet" href="~/css/night.css" type="text/css" title="Night">'
    '%s'
)


Tag = collections.namedtuple('Tag', 'name value')
Content = collections.namedtuple('Content', 'text keys type')

def make_input(input_file_name):
    if input_file_name == '-':
        return sys.stdin
    input_file_name = os.path.expanduser(input_file_name)
    import tarfile
    try:
        tf = tarfile.open(input_file_name)
    except:
        #probably this is not tar archive, open regular file
        return open(input_file_name)
    else:
        for tar in tf:
            if os.path.basename(tar.name) == 'dict.xdxf':
                return tf.extractfile(tar)
    raise IOError("%s doesn't look like a XDXF dictionary" % input_file_name)


VISUAL_TAGS = frozenset(('ar',
                         'k',
                         'opt',
                         'nu',
                         'def',
                         'pos',
                         'tense',
                         'tr',
                         'dtrn',
                         'kref',
                         'rref',
                         'iref',
                         'abr',
                         'c',
                         'ex',
                         'co',
                         'su'))

BLOCK_TAGS = frozenset(('k', ))

class XDXF():

    def __init__(self, input_file, skip_article_title=False, remove_newline=False):
        self.input_file = input_file
        self.skip_article_title = skip_article_title
        self.remove_newline = remove_newline

    def _tag_handler_ar(self, e, **_):
        e.set('class', e.tag)
        e.tag = 'div'

    def _tag_handler_c(self, child, **_):
        child.tag = 'span'
        color = child.get('c', '')
        child.attrib.clear()
        if color:
            child.set('style', 'color: %s;' % color)

    def _tag_handler_iref(self, child, **_):
        child.tag = 'a'

    def _tag_handler_kref(self, child, **_):
        child.tag = 'a'
        child.set('href', child.text)

    def _tag_handler_su(self, child, **_):
        child.tag = 'div'
        child.set('class', 'su')

    def _tag_handler_def(self, child, **_):
        child.tag = 'blockquote'

    def _tag_handler_abr(self, child, **kw):
        abbreviations = kw['abbreviations']
        child.tag = 'abbr'
        abr = child.text
        if abr in abbreviations:
            child.set('title', abbreviations[abr])

    def default_tag_handler(self, child, **_):
        if child.tag in VISUAL_TAGS:
            child.set('class', child.tag)
            child.tag = 'div' if child.tag in BLOCK_TAGS else 'span'

    def _mkabbrs(self, element):
        abbrs = {}
        for abrdef in element:
            if abrdef.tag.lower() == 'abr_def':
                value = abrdef.find('v')
                if value:
                    value_txt = value.text
                    for key in abrdef.findall('k'):
                        abbrs[key.text] = value_txt
        return abbrs

    def _transform_element(self, element, abbreviations):
        handler = getattr(self, '_tag_handler_'+element.tag.lower(),
                          self.default_tag_handler)
        handler(element, abbreviations=abbreviations)


    def _text(self, xdxf_element, abbreviations):
        element = deepcopy(xdxf_element)
        if self.skip_article_title:
            tail = ''
            for k in list(element.findall('k')):
                if k.tail:
                    tail += k.tail
                element.remove(k)
            tail = tail.lstrip()
            element.text = tail + element.text if element.text else tail
        self._transform_element(element, abbreviations)
        for child in element.iter():
            self._transform_element(child, abbreviations)

        txt = etree.tostring(element, encoding='unicode')
        if self.remove_newline:
            txt = txt.replace('\n', ' ')
        return (ARTICLE_TEMPLATE % txt).encode('utf8')

    def _mktitle(self, title_element, include_opts=()):
        title = title_element.text
        opt_i = -1
        for c in title_element:
            if c.tag == 'nu' and c.tail:
                if title:
                    title += c.tail
                else:
                    title = c.tail
            if c.tag == 'opt':
                opt_i += 1
                if opt_i in include_opts:
                    if title:
                        title += c.text
                    else:
                        title = c.text
                if c.tail:
                    if title:
                        title += c.tail
                    else:
                        title = c.tail
        return title

    def __iter__(self):
        yield from self.parse(self.input_file)

    def parse(self, f):
        abbreviations = {}
        for _, element in etree.iterparse(f):
            if element.tag == 'description':
                yield Tag('copyright', element.text or '')
                element.clear()

            if element.tag == 'full_name':
                label = element.text or ''
                yield Tag('label', label)
                yield Tag('uri', urllib.parse.quote(label.encode('utf-8'), safe=''))
                element.clear()

            if element.tag == 'xdxf':
                yield Tag('lang_to', element.get('lang_to', ''))
                yield Tag('lang_from', element.get('lang_from', ''))
                element.clear()

            if element.tag == 'abbreviations':
                abbreviations = self._mkabbrs(element)

            if element.tag == 'ar':
                txt = self._text(element, abbreviations)
                titles = []
                for title_element in element.findall('k'):
                    n_opts = len([c for c in title_element if c.tag == 'opt'])
                    if n_opts:
                        for j in range(n_opts+1):
                            for comb in combinations(range(n_opts), j):
                                titles.append(self._mktitle(title_element, comb))
                    else:
                        titles.append(self._mktitle(title_element))

                if titles:
                    yield Content(txt, titles, ARTICLE_CONTENT_TYPE)
                else:
                    logging.warn('No title found in article:\n%s',
                                 etree.tostring(element, encoding='utf8'))
                element.clear()


def parse_args():

    arg_parser = argparse.ArgumentParser()

    arg_parser.add_argument('input_file', type=str,
                            help='XDXF file name')

    arg_parser.add_argument(
        '--skip-article-title',
        action='store_true',
        help=('Do not include article key in rendered article: '
              'some XDXF dictionaries already inlude title in article text and '
              'need this to avoid title duplication'))

    arg_parser.add_argument(
        '--remove-newline',
        action='store_true',
        help=('Remove new line characters from article text'))

    arg_parser.add_argument('-o', '--output-file', type=str,
                            help='Name of output slob file')

    arg_parser.add_argument('-c', '--compression',
                            choices=['lzma2', 'zlib'],
                            default='zlib',
                            help='Name of compression to use. Default: %(default)s')

    arg_parser.add_argument('-b', '--bin-size',
                            type=int,
                            default=256,
                            help=('Minimum storage bin size in kilobytes. '
                                  'Default: %(default)s'))

    arg_parser.add_argument('-a', '--created-by', type=str,
                            default='',
                            help=('Value for created.by tag. '
                                  'Identifier (e.g. name or email) '
                                  'for slob file creator'))

    arg_parser.add_argument('-w', '--work-dir', type=str, default='.',
                            help=('Directory for temporary files '
                                  'created during compilation. '
                                  'Default: %(default)s'))

    return arg_parser.parse_args()


def main():

    logging.basicConfig()

    observer = slob.SimpleTimingObserver()

    args = parse_args()

    outname = args.output_file

    basename = os.path.basename(args.input_file)

    noext = basename

    if outname is None:
        while True:
            noext, _ext = os.path.splitext(noext)
            if not _ext:
                break
        outname = os.path.extsep.join((noext, 'slob'))

    def p(s):
        sys.stdout.write(s)
        sys.stdout.flush()

    with slob.create(outname,
                     compression=args.compression,
                     workdir=args.work_dir,
                     min_bin_size=args.bin_size*1024,
                     observer=observer) as slb:
        observer.begin('all')
        observer.begin('content')
        #create tags
        slb.tag('label', '')
        slb.tag('license.name', '')
        slb.tag('license.url', '')
        slb.tag('source', basename)
        slb.tag('uri', '')
        slb.tag('copyright', '')
        slb.tag('created.by', args.created_by)
        xdxf = XDXF(make_input(args.input_file),
                    skip_article_title=args.skip_article_title,
                    remove_newline=args.remove_newline)
        content_dir = os.path.dirname(__file__)
        slob.add_dir(slb, content_dir,
                     include_only={'js', 'css'},
                     prefix='~/')
        print('Adding content...')
        for i, item in enumerate(xdxf):
            if i % 100 == 0 and i: p('.')
            if i % 5000 == 0 and i: p(' {}\n'.format(i))
            if isinstance(item, Tag):
                slb.tag(item.name, item.value)
            else:
                slb.add(item.text, *item.keys, content_type=item.type)

    print('\nAll done in %s\n' % observer.end('all'))
