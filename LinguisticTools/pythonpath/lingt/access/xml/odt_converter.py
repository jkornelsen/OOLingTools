# -*- coding: Latin-1 -*-
#
# This file created June 22 2015 by Jim Kornelsen
#
# 16-Dec-15 JDK  Fixed bug: specify absolute path to xml files.
# 17-Dec-15 JDK  Implemented readContentFile with limited functionality.
# 22-Dec-15 JDK  Read a list of text nodes.
# 23-Dec-15 JDK  Added changeContentFile().
# 24-Dec-15 JDK  Added class OdtChanger.
# 20-Feb-16 JDK  Read complex and Asian font types.
# 21-Jun-16 JDK  Choose font type based on Unicode block.
# 13-Jul-16 JDK  Read font size.
# 21-Jul-16 JDK  Use ProcessingStyleItem instead of FontItem.

"""
Read and change an ODT file in XML format.
Call SEC_wrapper to do engine-based conversion.

This module exports:
    OdtReader
    OdtChanger
"""
import copy
import io
import logging
import os
import xml.dom.minidom
import xml.parsers.expat

from lingt.access.common.file_reader import FileReader
from lingt.access.xml import xmlutil
from lingt.app import exceptions
from lingt.app.data.bulkconv_structs import ProcessingStyleItem, ScopeType
from lingt.utils import letters
from lingt.utils import util
from lingt.utils.fontsize import FontSize

logger = logging.getLogger("lingt.access.odt_converter")


class BasicStyleType:
    """Not to be confused with bulkconv_structs.StyleType"""
    DEFAULT = 0  # document defaults, which perhaps are a kind of named style
    NAMED = 1  # for example "Heading 1"
    AUTOMATIC = 2  # also known as custom formatting


class OdtReader(FileReader):

    SUPPORTED_FORMATS = [("xml", "Unzipped Open Document Format (.odt)"),]

    def __init__(self, srcdir, scopeType, unoObjs):
        FileReader.__init__(self, unoObjs)
        self.srcdir = srcdir
        self.defaultStyleItem = None
        self.stylesDom = None
        self.contentDom = None
        self.scopeType = scopeType
        self.stylesDict = {}  # keys style name, value ProcessingStyleItem

    def _initData(self):
        """Elements are of type bulkconv_structs.ProcessingStyleItem."""
        self.data = []

    def _verifyDataFound(self):
        if not self.data:
            raise exceptions.DataNotFoundError(
                "Did not find any fonts in folder %s", self.srcdir)

    def _read(self):
        self.stylesDom = self.loadFile(
            os.path.join(self.srcdir, 'styles.xml'))
        self.progressBar.updatePercent(30)
        self.readStylesFile(self.stylesDom)
        self.progressBar.updatePercent(35)

        self.contentDom = self.loadFile(
            os.path.join(self.srcdir, 'content.xml'))
        self.progressBar.updatePercent(45)
        self.readContentFile(self.contentDom)
        self.progressBar.updatePercent(50)

    def loadFile(self, filepath):
        """Returns dom, raises exceptions.FileAccessError."""
        logger.debug(util.funcName('begin', args=filepath))
        if not os.path.exists(filepath):
            raise exceptions.FileAccessError(
                "Cannot find file %s", filepath)
        dom = None
        try:
            dom = xml.dom.minidom.parse(filepath)
        except xml.parsers.expat.ExpatError as exc:
            raise exceptions.FileAccessError(
                "Error reading file %s\n\n%s",
                filepath, str(exc).capitalize())
        if dom is None:
            raise exceptions.FileAccessError(
                "Error reading file %s", filepath)
        logger.debug(util.funcName('end'))
        return dom

    def readStylesFile(self, dom):
        """Read in styles.xml which defines named styles."""
        logger.debug(util.funcName('begin'))
        for style in dom.getElementsByTagName("style:default-style"):
            if style.getAttribute("style:family") == "paragraph":
                self.defaultStyleItem = self.read_text_props(
                    style, BasicStyleType.DEFAULT)
        for style in dom.getElementsByTagName("style:style"):
            xmlStyleName = style.getAttribute("style:name")
            parentStyleName = style.getAttribute("style:parent-style-name")
            self.add_named_style_from_parent(xmlStyleName, parentStyleName)
            self.read_text_props(style, BasicStyleType.NAMED)
        logger.debug(util.funcName('end'))

    def read_text_props(self, styleNode, basicStyleType):
        """Read style:text-properties nodes and store in self.stylesDict.
        Returns the ProcessingStyleItem for that style.
        """
        if (self.scopeType == ScopeType.PARASTYLE
                or self.scopeType == ScopeType.CHARSTYLE):
            if basicStyleType == BasicStyleType.AUTOMATIC:
                return
        elif self.scopeType == ScopeType.FONT_WITHOUT_STYLE:
            if basicStyleType == BasicStyleType.NAMED:
                return
        xmlStyleName = styleNode.getAttribute("style:name")
        if xmlStyleName in self.stylesDict:
            styleItem = self.stylesDict[xmlStyleName]
        else:
            styleItem = ProcessingStyleItem(self.scopeType, named)
        for textprop in styleNode.getElementsByTagName(
                "style:text-properties"):
            self.read_font_name(styleItem, textprop)
            self.read_font_size(styleItem, textprop)
        emptyStyleItem = ProcessingStyleItem(self.scopeType, named)
        return self.stylesDict.get(xmlStyleName, emptyStyleItem)

    def read_font_name(self, styleItem, textprop):
        """Modifies styleItem and self.stylesDict."""
        # Western is last in the list because it is the default.
        # The others will only be used if there are Complex or Asian
        # characters in the text.
        for xmlAttr, styleItemAttr, fontType in [
                ("style:font-name-asian", 'nameAsian', 'Asian'),
                ("style:font-name-complex", 'nameComplex', 'Complex'),
                ("style:font-name", 'nameStandard', 'Western')]:
            fontName = textprop.getAttribute(xmlAttr)
            if fontName:
                styleItem.fontName = fontName
                styleItem.fontType = fontType
                setattr(styleItem, styleItemAttr, fontName)
                self.stylesDict[xmlStyleName] = styleItem

    def read_font_size(self, styleItem, textprop):
        """Modifies styleItem and self.stylesDict."""
        for xmlAttr, styleItemAttr, fontType in [
                ("style:font-size-asian", 'sizeAsian', 'Asian'),
                ("style:font-size-complex", 'sizeComplex', 'Complex'),
                ("fo:font-size", 'sizeStandard', 'Western')]:
            fontSize = textprop.getAttribute(xmlAttr)
            if fontSize and fontSize.endswith("pt"):
                fontSize = fontSize[:-len("pt")]
                propSuffix = fontType
                if propSuffix == 'Western':
                    propSuffix = ""
                fontSizeObj = FontSize(fontSize, propSuffix, True)
                styleItem.size = fontSizeObj
                styleItem.fontType = fontType
                setattr(styleItem, styleItemAttr, fontSizeObj)
                self.stylesDict[xmlStyleName] = styleItem

    def add_named_style_from_parent(self, xmlStyleName, parentStyleName):
        """Add named style with attributes inherited from parent."""
        if parentStyleName not in self.stylesDict:
            return
        parentStyleItem = self.stylesDict[parentStyleName]
        if xmlStyleName in self.stylesDict:
            styleItem = self.stylesDict[xmlStyleName]
            for attrName in (
                    'nameStandard', 'nameComplex', 'nameAsian'):
                if parentStyleItem.getattr(attrName) != "(None)":
                    setattr(
                        styleItem, attrName,
                        parentStyleItem.getattr(attrName))
        else:
            styleItem = parentStyleItem
        self.stylesDict[xmlStyleName] = styleItem

    def readContentFile(self, dom):
        """Read in content.xml."""
        logger.debug(util.funcName('begin'))
        # Unlike common styles, automatic styles are not visible to the user.
        auto_styles = dom.getElementsByTagName("office:automatic-styles")[0]
        if auto_styles:
            for style in auto_styles.childNodes:
                self.read_text_props(style, BasicStyleType.AUTOMATIC)
        for paragraph in xmlutil.getElementsByTagNames(
                dom, ["text:h", "text:p"]):
            xmlStyleName = paragraph.getAttribute("text:style-name")
            paraStyleItem = self.stylesDict.get(
                xmlStyleName, self.defaultStyleItem)
            para_texts = xmlutil.getElemTextList(paragraph)
            styleItemAppender = StyleItemAppender(
                self.data, paraStyleItem, self.scopeType)
            styleItemAppender.add_texts(para_texts)
            for span in paragraph.getElementsByTagName("text:span"):
                xmlStyleName = span.getAttribute("text:style-name")
                spanStyleItem = self.stylesDict.get(
                    xmlStyleName, paraStyleItem)
                span_texts = xmlutil.getElemTextList(span)
                styleItemAppender = StyleItemAppender(
                    self.data, spanStyleItem, self.scopeType)
                styleItemAppender.add_texts(span_texts)
        #TODO: look for text:class-name, which is for paragraph styles.
        logger.debug(util.funcName('end'))


class StyleItemAppender:
    """Adds information to a list of ProcessingStyleItem objects.
    Modifies the list.
    """
    def __init__(self, styleItems, baseStyleItem, scopeType):
        """
        :param styleItems: list of ProcessingStyleItem objects to modify
        :param baseStyleItem: effective font of the node
        """
        self.styleItems = styleItems
        self.baseStyleItem = baseStyleItem
        self.scopeType = scopeType
        self.styleItemDict = {}  # keys like 'Western', values are StyleItem

    def add_texts_with_debug(self, textvals, xmlStyleName):
        logger.debug(
            util.funcName(args=(
                self.baseStyleItem.fontName, len(textvals), xmlStyleName)))
        self.add_texts(textvals)

    def add_texts(self, textvals):
        """Add content of a node for a particular effective font.
        :param textvals: text content of nodes
        """
        if (not self.baseStyleItem.fontName
                or self.baseStyleItem.fontName == "(None)"):
            return
        for newItem in self.get_items_for_each_type(textvals):
            self.add_item_data(newItem)

    def get_items_for_each_type(self, textvals):
        """The font type is based on the unicode block of a character,
        not just based on formatting.
        Because the font name may just fall back to defaults.
        """
        self.styleItemDict = {}
        for textval in textvals:
            text_of_one_type = ""
            curFontType = letters.TYPE_INDETERMINATE
            for c in textval:
                nextFontType = letters.getFontType(c, curFontType)
                if (nextFontType == curFontType
                        or curFontType == letters.TYPE_INDETERMINATE
                        or nextFontType == letters.TYPE_INDETERMINATE):
                    text_of_one_type += c
                elif text_of_one_type:
                    self.append_text_of_one_type(text_of_one_type, curFontType)
                    text_of_one_type = ""
                curFontType = nextFontType
            if text_of_one_type:
                self.append_text_of_one_type(text_of_one_type, curFontType)
        return list(self.styleItemDict.values())

    def append_text_of_one_type(self, textval, curFontType):
        FONT_TYPE_NUM_TO_NAME = {
            letters.TYPE_INDETERMINATE : 'Western',
            letters.TYPE_STANDARD : 'Western',
            letters.TYPE_COMPLEX : 'Complex',
            letters.TYPE_CJK : 'Asian'}
        fontTypeName = FONT_TYPE_NUM_TO_NAME[curFontType]
        styleItem = self.get_item_for_type(fontTypeName)
        styleItem.inputData.append(textval)

    def get_item_for_type(self, fontType):
        """Sets styleItem.fontType and styleItem.fontName."""
        if fontType in self.styleItemDict:
            return self.styleItemDict[fontType]
        ATTR_OF_FONT_TYPE = {
            'Asian' : 'nameAsian',
            'Complex' : 'nameComplex',
            'Western' : 'nameStandard'}
        newItem = copy.deepcopy(self.baseStyleItem)
        #if (nextFontType == letters.TYPE_COMPLEX
        #        or nextFontType == letters.TYPE_CJK):
        newItem.fontType = fontType
        #TODO: Do not get font of named styles if ScopeType.FONT_WITHOUT_STYLE.
        newItem.fontName = getattr(
            self.baseStyleItem, ATTR_OF_FONT_TYPE[fontType])
        self.styleItemDict[fontType] = newItem
        return newItem

    def add_item_data(self, newItem):
        for item in self.styleItems:
            if item == newItem:
                item.inputData.extend(newItem.inputData)
                break
        else:
            # newItem was not in self.styleItems, so add it.
            logger.debug("appending ProcessingStyleItem %s", newItem)
            self.styleItems.append(newItem)


class OdtChanger:
    def __init__(self, reader, styleChanges):
        """
        :param reader: type OdtReader
        :param styleChanges: list of elements type StyleChange
        """
        self.reader = reader
        self.styleChanges = styleChanges
        self.scopeType = reader.scopeType

    def makeChanges(self):
        logger.debug(util.funcName('begin'))
        num_changes = self.change_text(self.reader.contentDom)
        self.change_styles(self.reader.contentDom, self.reader.stylesDom)
        with io.open(os.path.join(self.reader.srcdir, 'styles.xml'),
                     mode="wt", encoding="utf-8") as f:
            self.reader.stylesDom.writexml(f, encoding="utf-8")
        with io.open(os.path.join(self.reader.srcdir, 'content.xml'),
                     mode="wt", encoding="utf-8") as f:
            self.reader.contentDom.writexml(f, encoding="utf-8")
        logger.debug(util.funcName('end'))
        return num_changes

    def change_text(self, dom):
        """Convert text in content.xml with EncConverters."""
        logger.debug(util.funcName('begin'))
        num_changes = 0
        for paragraph in xmlutil.getElementsByTagNames(
                dom, ["text:h", "text:p"]):
            xmlStyleName = paragraph.getAttribute("text:style-name")
            #logger.debug("para style name %s", xmlStyleName)
            paraStyleItem = self.reader.stylesDict.get(
                xmlStyleName, self.reader.defaultStyleItem)
            paraStyleChange = self.effective_styleChange(paraStyleItem)
            if paraStyleChange:
                logger.debug("Change for [%s]", xmlStyleName)
                for para_child in paragraph.childNodes:
                    if para_child.nodeType == para_child.TEXT_NODE:
                        if para_child.data in paraStyleChange.converted_data:
                            para_child.data = paraStyleChange.converted_data[
                                para_child.data]
                            num_changes += 1
            else:
                logger.debug("No change for [%s]", xmlStyleName)
            for span in paragraph.getElementsByTagName("text:span"):
                xmlStyleName = span.getAttribute("text:style-name")
                #logger.debug("span style name %s", xmlStyleName)
                spanStyleItem = self.reader.stylesDict.get(
                    xmlStyleName, paraStyleItem)
                spanStyleChange = self.effective_styleChange(spanStyleItem)
                if spanStyleChange:
                    for span_child in span.childNodes:
                        if span_child.nodeType == span_child.TEXT_NODE:
                            if (span_child.data in
                                    spanStyleChange.converted_data):
                                span_child.data = (
                                    spanStyleChange.converted_data[
                                        span_child.data])
                            num_changes += 1
        logger.debug(util.funcName('end'))
        return num_changes

    def change_styles(self, contentDom, stylesDom):
        """Change fonts and named styles."""
        #TODO: Distinguish between automatic and named styles.
        for style in (
                contentDom.getElementsByTagName("style:font-face") +
                stylesDom.getElementsByTagName("style:font-face")):
            fontName = style.getAttribute("style:name")
            for styleChange in self.styleChanges:
                if fontName == styleChange.styleItem.fontName:
                    style.setAttribute("style:name", styleChange.fontName)
                    style.setAttribute("svg:font-family", styleChange.fontName)
        for style in (
                contentDom.getElementsByTagName("style:style") +
                stylesDom.getElementsByTagName("style:default-style")):
            for textprop in style.getElementsByTagName(
                    "style:text-properties"):
                fontName = textprop.getAttribute("style:font-name")
                for styleChange in self.styleChanges:
                    if fontName == styleChange.styleItem.fontName:
                        textprop.setAttribute(
                            "style:font-name", styleChange.fontName)
                        #style.setAttribute(
                        #    "style:parent-style-name", styleChange.fontType)
                        #fontSize = textprop.getAttribute("fo:font-size")
                        #if fontSize and styleChange.size.isSpecified():
                        if styleChange.size.isSpecified():
                            textprop.setAttribute(
                                "fo:font-size", str(styleChange.size) + "pt")

    def effective_styleChange(self, processingStyleItem):
        """Returns the StyleChange object for the effective style,
        that is, the style specified by a paragraph node or
        overridden by a span node.
        """
        if processingStyleItem is None:
            logger.debug("processingStyleItem is None")
            return None
        logger.debug("Looking for %r", processingStyleItem)
        for styleChange in self.styleChanges:
            logger.debug("Checking %r", styleChange.styleItem)
            # This calls the overridden ProcessingStyleItem.__eq__().
            if processingStyleItem == styleChange.styleItem:
                logger.debug("Found %r", styleChange.styleItem)
                return styleChange
        logger.debug("Did not find processingStyleItem.")
        return None

