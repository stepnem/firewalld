# -*- coding: utf-8 -*-
#
# Copyright (C) 2011-2016 Red Hat, Inc.
#
# Authors:
# Thomas Woerner <twoerner@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

__all__ = [ "Helper", "helper_reader", "helper_writer" ]

import xml.sax as sax
import os
import io
import shutil

from firewall.config import ETC_FIREWALLD
from firewall.functions import u2b_if_py2
from firewall.core.io.io_object import PY2, IO_Object, \
    IO_Object_ContentHandler, IO_Object_XMLGenerator, check_port, \
    check_tcpudp, check_protocol, check_address
from firewall.core.logger import log
from firewall import errors
from firewall.errors import FirewallError

class Helper(IO_Object):
    IMPORT_EXPORT_STRUCTURE = (
        ( "version",  "" ),                   # s
        ( "short", "" ),                      # s
        ( "description", "" ),                # s
        ( "family", "", ),                    # s
        ( "ports", [ ( "", "" ), ], ),        # a(ss)
        )
    DBUS_SIGNATURE = '(ssssa(ss))'
    ADDITIONAL_ALNUM_CHARS = [ "_", "-" ]
    PARSER_REQUIRED_ELEMENT_ATTRS = {
        "short": None,
        "description": None,
        "helper": None,
        }
    PARSER_OPTIONAL_ELEMENT_ATTRS = {
        "helper": [ "name", "version", "family" ],
        "port": [ "port", "protocol" ],
        }

    def __init__(self):
        super(Helper, self).__init__()
        self.version = ""
        self.short = ""
        self.description = ""
        self.family = ""
        self.ports = [ ]

    def cleanup(self):
        self.version = ""
        self.short = ""
        self.description = ""
        self.family = ""
        del self.ports[:]

    def encode_strings(self):
        """ HACK. I haven't been able to make sax parser return
            strings encoded (because of python 2) instead of in unicode.
            Get rid of it once we throw out python 2 support."""
        self.version = u2b_if_py2(self.version)
        self.short = u2b_if_py2(self.short)
        self.description = u2b_if_py2(self.description)
        self.family = u2b_if_py2(self.family)
        self.ports = [(u2b_if_py2(po),u2b_if_py2(pr)) for (po,pr) in self.ports]

    def _check_ipv(self, ipv):
        ipvs = [ 'ipv4', 'ipv6' ]
        if ipv not in ipvs:
            raise FirewallError(errors.INVALID_IPV,
                                "'%s' not in '%s'" % (ipv, ipvs))

    def _check_config(self, config, item):
        if item == "ports":
            for port in config:
                check_port(port[0])
                check_tcpudp(port[1])

# PARSER

class helper_ContentHandler(IO_Object_ContentHandler):
    def startElement(self, name, attrs):
        IO_Object_ContentHandler.startElement(self, name, attrs)
        self.item.parser_check_element_attrs(name, attrs)
        if name == "helper":
            if "version" in attrs:
                self.item.version = attrs["version"]
            if "family" in attrs:
                self.item._check_ipv(attrs["family"])
                self.item.family = attrs["family"]
        elif name == "short":
            pass
        elif name == "description":
            pass
        elif name == "port":
            check_port(attrs["port"])
            check_tcpudp(attrs["protocol"])
            entry = (attrs["port"], attrs["protocol"])
            if entry not in self.item.ports:
                self.item.ports.append(entry)
            else:
                log.warning("Port '%s/%s' already set, ignoring.",
                            attrs["port"], attrs["protocol"])

def helper_reader(filename, path):
    helper = Helper()
    if not filename.endswith(".xml"):
        raise FirewallError(errors.INVALID_NAME,
                            "'%s' is missing .xml suffix" % filename)
    helper.name = filename[:-4]
    helper.check_name(helper.name)
    helper.filename = filename
    helper.path = path
    helper.builtin = False if path.startswith(ETC_FIREWALLD) else True
    helper.default = helper.builtin
    handler = helper_ContentHandler(helper)
    parser = sax.make_parser()
    parser.setContentHandler(handler)
    name = "%s/%s" % (path, filename)
    with open(name, "r") as f:
        try:
            parser.parse(f)
        except sax.SAXParseException as msg:
            raise FirewallError(errors.INVALID_HELPER,
                                "not a valid helper file: %s" % \
                                msg.getException())
    del handler
    del parser
    if PY2:
        helper.encode_strings()
    return helper

def helper_writer(helper, path=None):
    _path = path if path else helper.path

    if helper.filename:
        name = "%s/%s" % (_path, helper.filename)
    else:
        name = "%s/%s.xml" % (_path, helper.name)

    if os.path.exists(name):
        try:
            shutil.copy2(name, "%s.old" % name)
        except Exception as msg:
            log.error("Backup of file '%s' failed: %s", name, msg)

    dirpath = os.path.dirname(name)
    if dirpath.startswith(ETC_FIREWALLD) and not os.path.exists(dirpath):
        if not os.path.exists(ETC_FIREWALLD):
            os.mkdir(ETC_FIREWALLD, 0o750)
        os.mkdir(dirpath, 0o750)

    f = io.open(name, mode='wt', encoding='UTF-8')
    handler = IO_Object_XMLGenerator(f)
    handler.startDocument()

    # start helper element
    attrs = {}
    if helper.version and helper.version != "":
        attrs["version"] = helper.version
    if helper.family and helper.family != "":
        attrs["family"] = helper.family
    handler.startElement("helper", attrs)
    handler.ignorableWhitespace("\n")

    # short
    if helper.short and helper.short != "":
        handler.ignorableWhitespace("  ")
        handler.startElement("short", { })
        handler.characters(helper.short)
        handler.endElement("short")
        handler.ignorableWhitespace("\n")

    # description
    if helper.description and helper.description != "":
        handler.ignorableWhitespace("  ")
        handler.startElement("description", { })
        handler.characters(helper.description)
        handler.endElement("description")
        handler.ignorableWhitespace("\n")

    # ports
    for port in helper.ports:
        handler.ignorableWhitespace("  ")
        handler.simpleElement("port", { "port": port[0], "protocol": port[1] })
        handler.ignorableWhitespace("\n")

    # end helper element
    handler.endElement('helper')
    handler.ignorableWhitespace("\n")
    handler.endDocument()
    f.close()
    del handler
