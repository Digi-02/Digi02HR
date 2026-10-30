"""Lightweight Word, OpenDocument, RTF, and text exports for DigiDoc."""

from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


def _plain_inline(nodes):
    chunks = []
    for node in nodes:
        kind = node["type"]
        if kind == "text":
            chunks.append(node.get("text", ""))
        elif kind == "hardBreak":
            chunks.append("\n")
        elif kind == "image":
            alt = node.get("attrs", {}).get("alt", "")
            chunks.append(f"[Image: {alt}]" if alt else "[Image]")
    return "".join(chunks)


def _text_paragraphs(nodes):
    paragraphs = []
    for node in nodes:
        kind = node["type"]
        if kind in {"paragraph", "heading", "tableCell"}:
            paragraphs.append(_plain_inline(node.get("content", [])))
        elif kind in {"bulletList", "orderedList"}:
            for index, item in enumerate(node.get("content", []), 1):
                line = " ".join(_plain_inline(child.get("content", [])) for child in item.get("content", []))
                paragraphs.append(("• " if kind == "bulletList" else f"{index}. ") + line)
        elif kind == "table":
            for row in node.get("content", []):
                paragraphs.append("\t".join(_plain_inline(cell.get("content", [])) for cell in row.get("content", [])))
        elif kind == "hardBreak":
            paragraphs.append("\f")
        elif kind == "horizontalRule":
            paragraphs.append("─" * 32)
        elif kind in {"doc", "listItem"}:
            paragraphs.extend(_text_paragraphs(node.get("content", [])))
    return paragraphs


def plain_text(content):
    return "\n\n".join(_text_paragraphs(content.get("content", []))) + "\n"


def rtf_text(content):
    def escape(value):
        output = []
        for char in value:
            if char in "\\{}":
                output.append("\\" + char)
            elif char == "\n":
                output.append("\\line ")
            elif char == "\t":
                output.append("\\tab ")
            elif ord(char) < 128:
                output.append(char)
            else:
                encoded = char.encode("utf-16-le")
                for offset in range(0, len(encoded), 2):
                    unit = int.from_bytes(encoded[offset:offset + 2], "little")
                    output.append(f"\\u{unit if unit < 32768 else unit - 65536}?")
        return "".join(output)

    body = "\\par\n".join(escape(line) for line in _text_paragraphs(content.get("content", [])))
    return ("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Arial;}}\\viewkind4\\uc1\n" + body + "}").encode("ascii")


def _docx_run(parent, text, marks=()):
    run = ET.SubElement(parent, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r")
    props = ET.SubElement(run, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rPr")
    types = {mark["type"]: mark.get("attrs", {}) for mark in marks}
    for name, tag in (("bold", "b"), ("italic", "i"), ("underline", "u"), ("strike", "strike")):
        if name in types:
            attrs = {"{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val": "single"} if name == "underline" else {}
            ET.SubElement(props, f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}{tag}", attrs)
    if "fontSize" in types:
        size = str(types["fontSize"]["value"] * 2)
        ET.SubElement(props, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}sz", {"{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val": size})
    if "fontFamily" in types:
        font = types["fontFamily"]["value"]
        font = {"Helvetica": "Arial", "Times-Roman": "Times New Roman", "Courier": "Courier New"}.get(font, font)
        ET.SubElement(props, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts", {"{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ascii": font, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hAnsi": font})
    if "textColor" in types:
        ET.SubElement(props, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}color", {"{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val": types["textColor"]["color"][1:]})
    if "highlight" in types:
        ET.SubElement(props, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd", {"{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fill": types["highlight"]["color"][1:]})
    text_node = ET.SubElement(run, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
    if text[:1].isspace() or text[-1:].isspace():
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_node.text = text


def _docx_paragraph(parent, node=None, prefix=""):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    para = ET.SubElement(parent, f"{{{w}}}p")
    if node:
        attrs = node.get("attrs", {})
        props = ET.SubElement(para, f"{{{w}}}pPr")
        if node["type"] == "heading":
            ET.SubElement(props, f"{{{w}}}pStyle", {f"{{{w}}}val": f"Heading{node['level']}"})
        if attrs.get("align"):
            ET.SubElement(props, f"{{{w}}}jc", {f"{{{w}}}val": {"justify": "both"}.get(attrs["align"], attrs["align"])})
        if attrs.get("indent"):
            ET.SubElement(props, f"{{{w}}}ind", {f"{{{w}}}left": str(attrs["indent"] * 360)})
        if attrs.get("line_spacing"):
            line = {"single": "240", "1.15": "276", "1.5": "360", "double": "480"}[attrs["line_spacing"]]
            ET.SubElement(props, f"{{{w}}}spacing", {f"{{{w}}}line": line, f"{{{w}}}lineRule": "auto"})
        if len(props) == 0:
            para.remove(props)
        if prefix:
            _docx_run(para, prefix)
        for child in node.get("content", []):
            if child["type"] == "text":
                _docx_run(para, child.get("text", ""), child.get("marks", []))
            elif child["type"] == "hardBreak":
                run = ET.SubElement(para, f"{{{w}}}r")
                ET.SubElement(run, f"{{{w}}}br")
            elif child["type"] == "image":
                alt = child.get("attrs", {}).get("alt", "")
                _docx_run(para, f"[Image: {alt}]" if alt else "[Image]")
    return para


def _docx_blocks(parent, nodes):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    for node in nodes:
        kind = node["type"]
        if kind in {"paragraph", "heading"}:
            _docx_paragraph(parent, node)
        elif kind in {"bulletList", "orderedList"}:
            for index, item in enumerate(node.get("content", []), 1):
                children = item.get("content", [])
                if children:
                    for child_index, child in enumerate(children):
                        if child["type"] in {"paragraph", "heading"}:
                            _docx_paragraph(parent, child, ("• " if kind == "bulletList" else f"{index}. ") if child_index == 0 else "")
                        else:
                            _docx_blocks(parent, [child])
                else:
                    _docx_paragraph(parent, {"type": "paragraph", "content": []}, "• " if kind == "bulletList" else f"{index}. ")
        elif kind == "table":
            table = ET.SubElement(parent, f"{{{w}}}tbl")
            props = ET.SubElement(table, f"{{{w}}}tblPr")
            borders = ET.SubElement(props, f"{{{w}}}tblBorders")
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                ET.SubElement(borders, f"{{{w}}}{edge}", {f"{{{w}}}val": "single", f"{{{w}}}sz": "4", f"{{{w}}}color": "B7C0CC"})
            for row in node.get("content", []):
                tr = ET.SubElement(table, f"{{{w}}}tr")
                for cell in row.get("content", []):
                    tc = ET.SubElement(tr, f"{{{w}}}tc")
                    p = _docx_paragraph(tc)
                    for child in cell.get("content", []):
                        if child["type"] == "text":
                            _docx_run(p, child.get("text", ""), child.get("marks", []))
        elif kind == "hardBreak":
            p = ET.SubElement(parent, f"{{{w}}}p")
            run = ET.SubElement(p, f"{{{w}}}r")
            ET.SubElement(run, f"{{{w}}}br", {f"{{{w}}}type": "page"})
        elif kind == "horizontalRule":
            _docx_paragraph(parent, {"type": "paragraph", "content": [{"type": "text", "text": "─" * 32}]})
        elif kind == "image":
            alt = node.get("attrs", {}).get("alt", "")
            _docx_paragraph(parent, {"type": "paragraph", "content": [{"type": "text", "text": f"[Image: {alt}]" if alt else "[Image]"}]})


def docx(content):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ET.register_namespace("w", w)
    root = ET.Element(f"{{{w}}}document")
    body = ET.SubElement(root, f"{{{w}}}body")
    _docx_blocks(body, content.get("content", []))
    sect = ET.SubElement(body, f"{{{w}}}sectPr")
    ET.SubElement(sect, f"{{{w}}}pgSz", {f"{{{w}}}w": "11906", f"{{{w}}}h": "16838"})
    ET.SubElement(sect, f"{{{w}}}pgMar", {f"{{{w}}}top": "1134", f"{{{w}}}right": "1134", f"{{{w}}}bottom": "1134", f"{{{w}}}left": "1134", f"{{{w}}}header": "720", f"{{{w}}}footer": "720", f"{{{w}}}gutter": "0"})
    content_types = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'''
    rels = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    styles = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="20"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style></w:styles>'''
    content_types = content_types.replace(b"</Types>", b'<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    word_rels = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/styles.xml", styles)
        archive.writestr("word/_rels/document.xml.rels", word_rels)
    return buffer.getvalue()


def odt(content):
    ns = {
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
        "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    }
    for prefix, uri in ns.items():
        ET.register_namespace(prefix, uri)
    root = ET.Element(f"{{{ns['office']}}}document-content", {f"{{{ns['office']}}}version": "1.3"})
    automatic = ET.SubElement(root, f"{{{ns['office']}}}automatic-styles")
    body = ET.SubElement(root, f"{{{ns['office']}}}body")
    text_body = ET.SubElement(body, f"{{{ns['office']}}}text")

    def para(parent, node=None, prefix=""):
        kind = node["type"] if node else "paragraph"
        if kind == "heading":
            element = ET.SubElement(parent, f"{{{ns['text']}}}h", {f"{{{ns['text']}}}outline-level": str(node["level"])})
        else:
            element = ET.SubElement(parent, f"{{{ns['text']}}}p")
        if prefix:
            element.text = prefix
        if node:
            attrs = node.get("attrs", {})
            style_name = f"P{len(automatic)}"
            style_attrs = {f"{{{ns['style']}}}name": style_name, f"{{{ns['style']}}}family": "paragraph"}
            style = ET.SubElement(automatic, f"{{{ns['style']}}}style", style_attrs)
            prop = {}
            if attrs.get("align"):
                prop[f"{{{ns['fo']}}}text-align"] = attrs["align"]
            if attrs.get("indent"):
                prop[f"{{{ns['fo']}}}margin-left"] = f"{attrs['indent'] * 0.5}in"
            if attrs.get("line_spacing"):
                prop[f"{{{ns['fo']}}}line-height"] = {"single": "100%", "1.15": "115%", "1.5": "150%", "double": "200%"}[attrs["line_spacing"]]
            if prop:
                ET.SubElement(style, f"{{{ns['style']}}}paragraph-properties", prop)
            element.set(f"{{{ns['text']}}}style-name", style_name)
            for child in node.get("content", []):
                if child["type"] == "text":
                    marks = {mark["type"]: mark.get("attrs", {}) for mark in child.get("marks", [])}
                    if marks:
                        span_name = f"T{len(automatic)}"
                        span_style = ET.SubElement(automatic, f"{{{ns['style']}}}style", {f"{{{ns['style']}}}name": span_name, f"{{{ns['style']}}}family": "text"})
                        text_props = {}
                        if "bold" in marks: text_props[f"{{{ns['fo']}}}font-weight"] = "bold"
                        if "italic" in marks: text_props[f"{{{ns['fo']}}}font-style"] = "italic"
                        if "underline" in marks: text_props[f"{{{ns['style']}}}text-underline-style"] = "solid"
                        if "strike" in marks: text_props[f"{{{ns['style']}}}text-line-through-style"] = "solid"
                        if "textColor" in marks: text_props[f"{{{ns['fo']}}}color"] = marks["textColor"]["color"]
                        if "highlight" in marks: text_props[f"{{{ns['fo']}}}background-color"] = marks["highlight"]["color"]
                        if "fontSize" in marks: text_props[f"{{{ns['fo']}}}font-size"] = f"{marks['fontSize']['value']}pt"
                        if "fontFamily" in marks: text_props[f"{{{ns['fo']}}}font-family"] = {"Helvetica": "Arial", "Times-Roman": "Times New Roman", "Courier": "Courier New"}[marks["fontFamily"]["value"]]
                        ET.SubElement(span_style, f"{{{ns['style']}}}text-properties", text_props)
                        span = ET.SubElement(element, f"{{{ns['text']}}}span", {f"{{{ns['text']}}}style-name": span_name})
                        span.text = child.get("text", "")
                    else:
                        text_node = ET.SubElement(element, f"{{{ns['text']}}}span")
                        text_node.text = child.get("text", "")
                elif child["type"] == "hardBreak":
                    ET.SubElement(element, f"{{{ns['text']}}}line-break")
                elif child["type"] == "image":
                    alt = child.get("attrs", {}).get("alt", "")
                    fallback = ET.SubElement(element, f"{{{ns['text']}}}span")
                    fallback.text = f"[Image: {alt}]" if alt else "[Image]"
        return element

    def blocks(parent, nodes):
        for node in nodes:
            kind = node["type"]
            if kind in {"paragraph", "heading"}:
                para(parent, node)
            elif kind in {"bulletList", "orderedList"}:
                list_el = ET.SubElement(parent, f"{{{ns['text']}}}list")
                for item in node.get("content", []):
                    li = ET.SubElement(list_el, f"{{{ns['text']}}}list-item")
                    children = item.get("content", [])
                    if children:
                        for child in children:
                            if child["type"] in {"paragraph", "heading"}:
                                para(li, child)
                            else:
                                blocks(li, [child])
                    else:
                        para(li)
            elif kind == "table":
                table_el = ET.SubElement(parent, f"{{{ns['table']}}}table", {f"{{{ns['table']}}}name": f"Table{len(parent)}"})
                for row in node.get("content", []):
                    row_el = ET.SubElement(table_el, f"{{{ns['table']}}}table-row")
                    for cell in row.get("content", []):
                        cell_el = ET.SubElement(row_el, f"{{{ns['table']}}}table-cell")
                        para(cell_el, {"type": "paragraph", "content": cell.get("content", [])})
            elif kind == "hardBreak":
                para(parent, {"type": "paragraph", "content": [{"type": "text", "text": ""}]})
            elif kind == "horizontalRule":
                para(parent, {"type": "paragraph", "content": [{"type": "text", "text": "─" * 32}]})
            elif kind == "image":
                alt = node.get("attrs", {}).get("alt", "")
                para(parent, {"type": "paragraph", "content": [{"type": "text", "text": f"[Image: {alt}]" if alt else "[Image]"}]})

    blocks(text_body, content.get("content", []))
    styles_root = ET.Element(f"{{{ns['office']}}}document-styles", {f"{{{ns['office']}}}version": "1.3"})
    common_styles = ET.SubElement(styles_root, f"{{{ns['office']}}}styles")
    default_style = ET.SubElement(common_styles, f"{{{ns['style']}}}default-style", {f"{{{ns['style']}}}family": "paragraph"})
    ET.SubElement(default_style, f"{{{ns['style']}}}paragraph-properties", {f"{{{ns['fo']}}}margin-top": "0in", f"{{{ns['fo']}}}margin-bottom": "0.08in"})
    ET.SubElement(default_style, f"{{{ns['style']}}}text-properties", {f"{{{ns['fo']}}}font-family": "Arial", f"{{{ns['fo']}}}font-size": "10pt"})
    styles_xml = ET.tostring(styles_root, encoding="utf-8", xml_declaration=True)
    manifest = f'''<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/><manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/></manifest:manifest>'''
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=ZIP_STORED)
        archive.writestr("content.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True), compress_type=ZIP_DEFLATED)
        archive.writestr("styles.xml", styles_xml, compress_type=ZIP_DEFLATED)
        archive.writestr("META-INF/manifest.xml", manifest.encode("utf-8"), compress_type=ZIP_DEFLATED)
    return buffer.getvalue()
