"""Lightweight Word, OpenDocument, RTF, and text exports for DigiDoc."""

from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile
import re
import unicodedata
from PIL import Image, ImageOps


def _safe_alt(value):
    return "".join(ch for ch in str(value or "") if unicodedata.category(ch) not in {"Cc", "Cf", "Cs"})[:300]


def _asset_bytes(node, assets):
    if not assets:
        return None
    asset = assets.get(node.get("attrs", {}).get("asset_id"))
    if not isinstance(asset, dict):
        return None
    data = asset.get("data")
    if not isinstance(data, bytes) or not data or len(data) > 8 * 1024 * 1024:
        return None
    return data


def _prepared_image(node, assets):
    data = _asset_bytes(node, assets)
    if data is None:
        return None
    attrs = node.get("attrs", {})
    try:
        with Image.open(BytesIO(data)) as source:
            source.load()
            ratio = {"square": 1, "landscape": 16 / 9, "portrait": 3 / 4}.get(attrs.get("crop", "none"))
            if ratio:
                target_w = 1200
                source = ImageOps.fit(source.convert("RGBA" if "A" in source.getbands() else "RGB"), (target_w, max(1, round(target_w / ratio))), centering=(.5, .5))
            out = BytesIO()
            fmt = "PNG" if source.mode in {"RGBA", "LA"} else "JPEG"
            if fmt == "JPEG":
                source = source.convert("RGB")
                source.save(out, format=fmt, quality=90, optimize=True)
            else:
                source.save(out, format=fmt, optimize=True)
            return {"data": out.getvalue(), "format": fmt.lower(), "width": source.width, "height": source.height}
    except Exception:
        return None


def _plain_inline(nodes, assets=None):
    chunks = []
    for node in nodes:
        kind = node["type"]
        if kind == "text":
            chunks.append(node.get("text", ""))
        elif kind == "hardBreak":
            chunks.append("\n")
        elif kind == "image":
            alt = _safe_alt(node.get("attrs", {}).get("alt", ""))
            label = f"[Image: {alt}]" if alt else "[Image]"
            if _asset_bytes(node, assets) is None:
                label = f"[Image unavailable: {alt}]" if alt else "[Image unavailable]"
            attrs = node.get("attrs", {})
            chunks.append(("\n" * min(5, attrs.get("space_before_pt", 0) // 40)) + f"\n{label}\n" + ("\n" * min(5, attrs.get("space_after_pt", 0) // 40)))
    return "".join(chunks)


def _text_paragraphs(nodes, assets=None):
    paragraphs = []
    for node in nodes:
        kind = node["type"]
        if kind in {"paragraph", "heading", "tableCell"}:
            paragraphs.append(_plain_inline(node.get("content", []), assets))
            if node.get("attrs", {}).get("space_before_pt") or node.get("attrs", {}).get("space_after_pt"):
                # Spacing is represented by at most five blank lines in plain text.
                pass
        elif kind == "image":
            alt = _safe_alt(node.get("attrs", {}).get("alt", ""))
            label = f"[Image: {alt}]" if alt else "[Image]"
            if _asset_bytes(node, assets) is None:
                label = f"[Image unavailable: {alt}]" if alt else "[Image unavailable]"
            before = min(5, node.get("attrs", {}).get("space_before_pt", 0) // 40)
            after = min(5, node.get("attrs", {}).get("space_after_pt", 0) // 40)
            paragraphs.append(("\n" * before) + label + ("\n" * after))
        elif kind in {"bulletList", "orderedList"}:
            checklist = kind == "bulletList" and node.get("attrs", {}).get("list_style") == "checklist"
            for index, item in enumerate(node.get("content", []), 1):
                line = " ".join(_plain_inline(child.get("content", []), assets) for child in item.get("content", []))
                marker = "[ ] " if checklist else ("- " if kind == "bulletList" else f"{index}. ")
                paragraphs.append(marker + line)
        elif kind == "table":
            for row in node.get("content", []):
                paragraphs.append("\t".join(_plain_inline(cell.get("content", [])) for cell in row.get("content", [])))
        elif kind == "hardBreak":
            paragraphs.append("\f")
        elif kind == "horizontalRule":
            paragraphs.append("─" * 32)
        elif kind in {"doc", "listItem"}:
            paragraphs.extend(_text_paragraphs(node.get("content", []), assets))
    return paragraphs


def plain_text(content, assets=None):
    return "\n\n".join(_text_paragraphs(content.get("content", []), assets)) + "\n"


def rtf_text(content, assets=None):
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

    def rtf_image(node):
        prepared = _prepared_image(node, assets)
        attrs = node.get("attrs", {})
        if prepared is None:
            alt = _safe_alt(attrs.get("alt", ""))
            return escape(f"[Image unavailable: {alt}]" if alt else "[Image unavailable]")
        hex_data = prepared["data"].hex()
        if len(hex_data) > 16 * 1024 * 1024 or not re.fullmatch(r"[0-9a-f]+", hex_data):
            return escape("[Image unavailable]")
        width_goal = max(1, round(450 * 20 * attrs.get("width_percent", 100) / 100))
        height_goal = max(1, round(width_goal * prepared["height"] / max(1, prepared["width"])))
        blip = "pngblip" if prepared["format"] == "png" else "jpegblip"
        return (f"\\sb{attrs.get('space_before_pt', 0) * 20}\\sa{attrs.get('space_after_pt', 0) * 20}"
                f"\\{ {'left':'ql','center':'qc','right':'qr'}.get(attrs.get('align', 'center'), 'qc') }"
                f"{{\\pict\\{blip}\\picw{prepared['width']}\\pich{prepared['height']}"
                f"\\picwgoal{width_goal}\\pichgoal{height_goal}\n{hex_data}}}")

    def inline(nodes):
        pieces = []
        for node in nodes:
            kind = node["type"]
            if kind == "text": pieces.append(escape(node.get("text", "")))
            elif kind == "hardBreak": pieces.append("\\line ")
            elif kind == "image": pieces.append(rtf_image(node))
        return "".join(pieces)

    def blocks(nodes):
        result = []
        for node in nodes:
            kind = node["type"]
            if kind in {"paragraph", "heading", "tableCell"}:
                attrs = node.get("attrs", {})
                result.append(f"\\sb{attrs.get('space_before_pt', 0) * 20}\\sa{attrs.get('space_after_pt', 0) * 20}" + inline(node.get("content", [])))
            elif kind == "image":
                result.append(rtf_image(node))
            elif kind in {"doc", "listItem"}:
                result.extend(blocks(node.get("content", [])))
            elif kind in {"bulletList", "orderedList"}:
                for index, item in enumerate(node.get("content", []), 1):
                    marker = "[ ] " if kind == "bulletList" and node.get("attrs", {}).get("list_style") == "checklist" else ("- " if kind == "bulletList" else f"{index}. ")
                    result.append(escape(marker) + " ".join(inline(child.get("content", [])) for child in item.get("content", [])))
            elif kind == "hardBreak": result.append("\\page ")
            elif kind == "horizontalRule": result.append(escape("—" * 32))
        return result

    body = "\\par\n".join(blocks(content.get("content", [])))
    output = ("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Arial;}}\\viewkind4\\uc1\n" + body + "}").encode("ascii")
    _validate_rtf(output)
    return output


def _validate_rtf(data):
    if not isinstance(data, bytes) or len(data) > 25 * 1024 * 1024 or not data.startswith(b"{\\rtf1"):
        raise ValueError("Invalid RTF document")
    allowed = {b"rtf", b"ansi", b"deff", b"fonttbl", b"f", b"viewkind", b"uc", b"par", b"line", b"tab", b"u", b"sb", b"sa", b"ql", b"qc", b"qr", b"pict", b"pngblip", b"jpegblip", b"picw", b"pich", b"picwgoal", b"pichgoal"}
    control_scan = re.sub(rb"\\\\", b"", data)
    for match in re.finditer(rb"\\([A-Za-z]+)(-?\d+)? ?", control_scan):
        if match.group(1).lower() not in allowed:
            raise ValueError("Unsupported RTF control word")
    for match in re.finditer(rb"\\pict.*?\n([^{}\\\s]+)\}", data, re.S):
        if len(match.group(1)) > 16 * 1024 * 1024 or not re.fullmatch(rb"[0-9a-fA-F]+", match.group(1)):
            raise ValueError("Invalid RTF image data")
    depth = 0
    escaped = False
    for byte in data:
        char = chr(byte)
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "{": depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0: raise ValueError("Invalid RTF groups")
    if depth != 0: raise ValueError("Invalid RTF groups")


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


def _docx_image(parent, node, assets, media, image_rels, counter):
    prepared = _prepared_image(node, assets)
    if prepared is None:
        alt = _safe_alt(node.get("attrs", {}).get("alt", ""))
        _docx_run(parent, f"[Image unavailable: {alt}]" if alt else "[Image unavailable]")
        return
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    wp = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    pic = "http://schemas.openxmlformats.org/drawingml/2006/picture"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    counter[0] += 1
    image_name = f"image{counter[0]}.{prepared['format']}"
    rid = f"rIdImage{counter[0]}"
    media[image_name] = prepared["data"]
    image_rels.append((rid, f"media/{image_name}"))
    attrs = node.get("attrs", {})
    width = max(1, round(451 * 12700 * attrs.get("width_percent", 100) / 100))
    height = max(1, round(width * prepared["height"] / max(1, prepared["width"])))
    run = ET.SubElement(parent, f"{{{w}}}r")
    drawing = ET.SubElement(run, f"{{{w}}}drawing")
    inline = ET.SubElement(drawing, f"{{{wp}}}inline", {"distT":"0", "distB":"0", "distL":"0", "distR":"0"})
    ET.SubElement(inline, f"{{{wp}}}extent", {"cx":str(width), "cy":str(height)})
    ET.SubElement(inline, f"{{{wp}}}docPr", {"id":str(counter[0]), "name":image_name, "descr":_safe_alt(attrs.get("alt", ""))})
    frame = ET.SubElement(inline, f"{{{wp}}}cNvGraphicFramePr")
    ET.SubElement(frame, f"{{{a}}}graphicFrameLocks", {"noChangeAspect":"1"})
    graphic = ET.SubElement(inline, f"{{{a}}}graphic")
    graphic_data = ET.SubElement(graphic, f"{{{a}}}graphicData", {"uri":pic})
    picture = ET.SubElement(graphic_data, f"{{{pic}}}pic")
    nv = ET.SubElement(picture, f"{{{pic}}}nvPicPr")
    ET.SubElement(nv, f"{{{pic}}}cNvPr", {"id":str(counter[0]), "name":image_name, "descr":_safe_alt(attrs.get("alt", ""))})
    ET.SubElement(nv, f"{{{pic}}}cNvPicPr")
    fill = ET.SubElement(picture, f"{{{pic}}}blipFill")
    ET.SubElement(fill, f"{{{a}}}blip", {f"{{{r}}}embed":rid})
    stretch = ET.SubElement(fill, f"{{{a}}}stretch")
    ET.SubElement(stretch, f"{{{a}}}fillRect")
    shape = ET.SubElement(picture, f"{{{pic}}}spPr")
    xfrm = ET.SubElement(shape, f"{{{a}}}xfrm")
    ET.SubElement(xfrm, f"{{{a}}}off", {"x":"0", "y":"0"})
    ET.SubElement(xfrm, f"{{{a}}}ext", {"cx":str(width), "cy":str(height)})
    geom = ET.SubElement(shape, f"{{{a}}}prstGeom", {"prst":"rect"})
    ET.SubElement(geom, f"{{{a}}}avLst")


def _docx_paragraph(parent, node=None, prefix="", assets=None, media=None, image_rels=None, counter=None):
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
        if attrs.get("space_before_pt") or attrs.get("space_after_pt"):
            spacing = props.find(f"{{{w}}}spacing")
            if spacing is None:
                spacing = ET.SubElement(props, f"{{{w}}}spacing")
            spacing.set(f"{{{w}}}before", str(attrs.get("space_before_pt", 0) * 20))
            spacing.set(f"{{{w}}}after", str(attrs.get("space_after_pt", 0) * 20))
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
                image_attrs = child.get("attrs", {})
                if image_attrs.get("align"):
                    props = para.find(f"{{{w}}}pPr")
                    if props is None:
                        props = ET.SubElement(para, f"{{{w}}}pPr")
                    jc = props.find(f"{{{w}}}jc")
                    if jc is None:
                        jc = ET.SubElement(props, f"{{{w}}}jc")
                    jc.set(f"{{{w}}}val", {"justify":"both"}.get(image_attrs["align"], image_attrs["align"]))
                image_spacing = para.find(f"{{{w}}}pPr/{{{w}}}spacing")
                if image_spacing is None:
                    props = para.find(f"{{{w}}}pPr")
                    if props is None:
                        props = ET.SubElement(para, f"{{{w}}}pPr")
                    image_spacing = ET.SubElement(props, f"{{{w}}}spacing")
                image_spacing.set(f"{{{w}}}before", str(image_attrs.get("space_before_pt", 0) * 20))
                image_spacing.set(f"{{{w}}}after", str(image_attrs.get("space_after_pt", 0) * 20))
                _docx_image(para, child, assets, media, image_rels, counter)
    return para


def _docx_blocks(parent, nodes, assets=None, media=None, image_rels=None, counter=None):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    for node in nodes:
        kind = node["type"]
        if kind in {"paragraph", "heading"}:
            _docx_paragraph(parent, node, assets=assets, media=media, image_rels=image_rels, counter=counter)
        elif kind in {"bulletList", "orderedList"}:
            checklist = kind == "bulletList" and node.get("attrs", {}).get("list_style") == "checklist"
            for index, item in enumerate(node.get("content", []), 1):
                children = item.get("content", [])
                marker = "[ ] " if checklist else ("- " if kind == "bulletList" else f"{index}. ")
                if children:
                    for child_index, child in enumerate(children):
                        if child["type"] in {"paragraph", "heading"}:
                            _docx_paragraph(parent, child, marker if child_index == 0 else "", assets, media, image_rels, counter)
                        else:
                            _docx_blocks(parent, [child], assets, media, image_rels, counter)
                else:
                    _docx_paragraph(parent, {"type": "paragraph", "content": []}, marker, assets, media, image_rels, counter)
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
                    _docx_paragraph(tc, {"type":"paragraph", "content":cell.get("content", [])}, assets=assets, media=media, image_rels=image_rels, counter=counter)
        elif kind == "hardBreak":
            p = ET.SubElement(parent, f"{{{w}}}p")
            run = ET.SubElement(p, f"{{{w}}}r")
            ET.SubElement(run, f"{{{w}}}br", {f"{{{w}}}type": "page"})
        elif kind == "horizontalRule":
            _docx_paragraph(parent, {"type": "paragraph", "content": [{"type": "text", "text": "─" * 32}]})
        elif kind == "image":
            alt = node.get("attrs", {}).get("alt", "")
            _docx_paragraph(parent, {"type": "paragraph", "attrs":node.get("attrs", {}), "content": [{"type": "image", "attrs":node.get("attrs", {})}]}, assets=assets, media=media, image_rels=image_rels, counter=counter)


def docx(content, assets=None):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    for prefix, namespace in (("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"), ("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"), ("a", "http://schemas.openxmlformats.org/drawingml/2006/main"), ("pic", "http://schemas.openxmlformats.org/drawingml/2006/picture")):
        ET.register_namespace(prefix, namespace)
    ET.register_namespace("w", w)
    root = ET.Element(f"{{{w}}}document")
    body = ET.SubElement(root, f"{{{w}}}body")
    media, image_rels, counter = {}, [], [0]
    _docx_blocks(body, content.get("content", []), assets, media, image_rels, counter)
    sect = ET.SubElement(body, f"{{{w}}}sectPr")
    ET.SubElement(sect, f"{{{w}}}pgSz", {f"{{{w}}}w": "11906", f"{{{w}}}h": "16838"})
    ET.SubElement(sect, f"{{{w}}}pgMar", {f"{{{w}}}top": "1134", f"{{{w}}}right": "1134", f"{{{w}}}bottom": "1134", f"{{{w}}}left": "1134", f"{{{w}}}header": "720", f"{{{w}}}footer": "720", f"{{{w}}}gutter": "0"})
    content_types = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Default Extension="jpeg" ContentType="image/jpeg"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'''
    rels = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    styles = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="20"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style></w:styles>'''
    content_types = content_types.replace(b"</Types>", b'<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    rel_items = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>']
    rel_items.extend(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{target}"/>' for rid, target in image_rels)
    word_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rel_items) + "</Relationships>").encode("utf-8")
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/styles.xml", styles)
        archive.writestr("word/_rels/document.xml.rels", word_rels)
        for name, data in media.items():
            archive.writestr(f"word/media/{name}", data)
    return buffer.getvalue()


def odt(content, assets=None):
    ns = {
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
        "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
        "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
        "xlink": "http://www.w3.org/1999/xlink",
    }
    for prefix, uri in ns.items():
        ET.register_namespace(prefix, uri)
    for prefix, uri in ns.items():
        ET.register_namespace(prefix, uri)
    root = ET.Element(f"{{{ns['office']}}}document-content", {f"{{{ns['office']}}}version": "1.3"})
    automatic = ET.SubElement(root, f"{{{ns['office']}}}automatic-styles")
    body = ET.SubElement(root, f"{{{ns['office']}}}body")
    text_body = ET.SubElement(body, f"{{{ns['office']}}}text")

    pictures = {}
    image_counter = [0]

    def image_frame(parent, child):
        prepared = _prepared_image(child, assets)
        attrs = child.get("attrs", {})
        if prepared is None:
            alt = _safe_alt(attrs.get("alt", ""))
            fallback = ET.SubElement(parent, f"{{{ns['text']}}}span")
            fallback.text = f"[Image unavailable: {alt}]" if alt else "[Image unavailable]"
            return
        image_counter[0] += 1
        name = f"Pictures/image{image_counter[0]}.{prepared['format']}"
        pictures[name] = prepared["data"]
        width_in = 6.27 * attrs.get("width_percent", 100) / 100
        height_in = width_in * prepared["height"] / max(1, prepared["width"])
        frame = ET.SubElement(parent, f"{{{ns['draw']}}}frame", {
            f"{{{ns['draw']}}}name": f"Image{image_counter[0]}",
            f"{{{ns['text']}}}anchor-type": "as-char",
            f"{{{ns['svg']}}}width": f"{width_in:.3f}in",
            f"{{{ns['svg']}}}height": f"{height_in:.3f}in",
            f"{{{ns['draw']}}}style-name": "",
        })
        ET.SubElement(frame, f"{{{ns['svg']}}}title").text = _safe_alt(attrs.get("alt", ""))
        ET.SubElement(frame, f"{{{ns['draw']}}}image", {
            f"{{{ns['xlink']}}}href": name,
            f"{{{ns['xlink']}}}type": "simple",
            f"{{{ns['xlink']}}}show": "embed",
            f"{{{ns['xlink']}}}actuate": "onLoad",
        })

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
            if attrs.get("space_before_pt"):
                prop[f"{{{ns['fo']}}}margin-top"] = f"{attrs['space_before_pt']}pt"
            if attrs.get("space_after_pt"):
                prop[f"{{{ns['fo']}}}margin-bottom"] = f"{attrs['space_after_pt']}pt"
            for image_node in node.get("content", []):
                if image_node.get("type") != "image":
                    continue
                image_attrs = image_node.get("attrs", {})
                if image_attrs.get("space_before_pt"):
                    prop.setdefault(f"{{{ns['fo']}}}margin-top", f"{image_attrs['space_before_pt']}pt")
                if image_attrs.get("space_after_pt"):
                    prop.setdefault(f"{{{ns['fo']}}}margin-bottom", f"{image_attrs['space_after_pt']}pt")
                if image_attrs.get("align"):
                    prop.setdefault(f"{{{ns['fo']}}}text-align", image_attrs["align"])
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
                        if "fontFamily" in marks: text_props[f"{{{ns['fo']}}}font-family"] = {"Helvetica": "Arial", "Times-Roman": "Times New Roman", "Courier": "Courier New"}.get(marks["fontFamily"]["value"], marks["fontFamily"]["value"])
                        ET.SubElement(span_style, f"{{{ns['style']}}}text-properties", text_props)
                        span = ET.SubElement(element, f"{{{ns['text']}}}span", {f"{{{ns['text']}}}style-name": span_name})
                        span.text = child.get("text", "")
                    else:
                        text_node = ET.SubElement(element, f"{{{ns['text']}}}span")
                        text_node.text = child.get("text", "")
                elif child["type"] == "hardBreak":
                    ET.SubElement(element, f"{{{ns['text']}}}line-break")
                elif child["type"] == "image":
                    image_attrs = child.get("attrs", {})
                    paragraph_properties = style.find(f"{{{ns['style']}}}paragraph-properties")
                    if paragraph_properties is None:
                        paragraph_properties = ET.SubElement(style, f"{{{ns['style']}}}paragraph-properties")
                    if image_attrs.get("align"):
                        paragraph_properties.set(f"{{{ns['fo']}}}text-align", image_attrs["align"])
                    if image_attrs.get("space_before_pt"):
                        paragraph_properties.set(f"{{{ns['fo']}}}margin-top", f"{image_attrs['space_before_pt']}pt")
                    if image_attrs.get("space_after_pt"):
                        paragraph_properties.set(f"{{{ns['fo']}}}margin-bottom", f"{image_attrs['space_after_pt']}pt")
                    image_frame(element, child)
        return element

    def blocks(parent, nodes):
        for node in nodes:
            kind = node["type"]
            if kind in {"paragraph", "heading"}:
                para(parent, node)
            elif kind in {"bulletList", "orderedList"}:
                checklist = kind == "bulletList" and node.get("attrs", {}).get("list_style") == "checklist"
                list_el = ET.SubElement(parent, f"{{{ns['text']}}}list")
                for item in node.get("content", []):
                    li = ET.SubElement(list_el, f"{{{ns['text']}}}list-item")
                    children = item.get("content", [])
                    if children:
                        for child_index, child in enumerate(children):
                            if child["type"] in {"paragraph", "heading"}:
                                para(li, child, "[ ] " if checklist and child_index == 0 else "")
                            else:
                                blocks(li, [child])
                    else:
                        para(li, prefix="[ ] " if checklist else "")
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
                para(parent, {"type": "paragraph", "attrs":node.get("attrs", {}), "content": [node]})

    blocks(text_body, content.get("content", []))
    styles_root = ET.Element(f"{{{ns['office']}}}document-styles", {f"{{{ns['office']}}}version": "1.3"})
    common_styles = ET.SubElement(styles_root, f"{{{ns['office']}}}styles")
    default_style = ET.SubElement(common_styles, f"{{{ns['style']}}}default-style", {f"{{{ns['style']}}}family": "paragraph"})
    ET.SubElement(default_style, f"{{{ns['style']}}}paragraph-properties", {f"{{{ns['fo']}}}margin-top": "0in", f"{{{ns['fo']}}}margin-bottom": "0.08in"})
    ET.SubElement(default_style, f"{{{ns['style']}}}text-properties", {f"{{{ns['fo']}}}font-family": "Arial", f"{{{ns['fo']}}}font-size": "10pt"})
    styles_xml = ET.tostring(styles_root, encoding="utf-8", xml_declaration=True)
    picture_entries = "".join(f'<manifest:file-entry manifest:full-path="{name}" manifest:media-type="image/{"jpeg" if name.endswith("jpeg") else "png"}"/>' for name in pictures)
    manifest = f'''<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/><manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>{picture_entries}</manifest:manifest>'''
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=ZIP_STORED)
        archive.writestr("content.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True), compress_type=ZIP_DEFLATED)
        archive.writestr("styles.xml", styles_xml, compress_type=ZIP_DEFLATED)
        archive.writestr("META-INF/manifest.xml", manifest.encode("utf-8"), compress_type=ZIP_DEFLATED)
        for name, data in pictures.items():
            archive.writestr(name, data, compress_type=ZIP_DEFLATED)
    return buffer.getvalue()
