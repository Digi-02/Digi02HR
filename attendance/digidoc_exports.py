"""Lightweight Word, OpenDocument, RTF, and text exports for DigiDoc."""

from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile
import html
import re
import unicodedata
from PIL import Image, ImageOps


PAGE_SIZE_TWIPS = {
    "A4": (11906, 16838), "A5": (8391, 11906), "A3": (16838, 23811),
    "Letter": (12240, 15840), "Legal": (12240, 20160),
}
DEFAULT_MARGINS_CM = {"top_cm": 2.5, "right_cm": 2.5, "bottom_cm": 2.5, "left_cm": 2.5}


def _ordered_marker(style, number):
    if style in {"lower-alpha", "upper-alpha"}:
        base = 97 if style == "lower-alpha" else 65
        value, letters = number, ""
        while value > 0:
            value -= 1
            letters = chr(base + value % 26) + letters
            value //= 26
        return letters + "."
    def roman(value):
        result = ""
        for amount, token in ((1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")):
            while value >= amount: result += token; value -= amount
        return result
    if style in {"lower-roman", "upper-roman"}:
        token = roman(max(1, min(number, 3999)))
        return (token.lower() if style == "lower-roman" else token) + "."
    return f"{number}."


def _layout_attrs(content):
    attrs = content.get("attrs", {})
    size = attrs.get("page_size", "A4")
    orientation = attrs.get("orientation", "portrait")
    margins = {**DEFAULT_MARGINS_CM, **attrs.get("margins", {})}
    if orientation == "landscape":
        width, height = PAGE_SIZE_TWIPS[size]
        page = (height, width)
    else:
        page = PAGE_SIZE_TWIPS[size]
    return size, orientation, margins, page


def _table_columns(node):
    rows = node.get("content", [])
    count = max((sum(cell.get("attrs", {}).get("colspan", 1) for cell in row.get("content", [])) for row in rows), default=1)
    supplied = node.get("attrs", {}).get("column_widths", [])
    if len(supplied) == count:
        return supplied
    base, remainder = divmod(100, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


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

    def list_lines(node, depth=0):
        kind = node["type"]
        checklist = kind == "bulletList" and node.get("attrs", {}).get("list_style") == "checklist"
        start = node.get("attrs", {}).get("start", 1)
        for index, item in enumerate(node.get("content", [])):
            children = item.get("content", [])
            text_parts = [_plain_inline(child.get("content", []), assets) for child in children if child["type"] in {"paragraph", "heading"}]
            list_style = node.get("attrs", {}).get("list_style", "decimal" if kind == "orderedList" else "disc")
            marker = "[ ] " if checklist else (({"disc":"\u2022", "circle":"\u25e6", "square":"\u25aa"}.get(list_style, "\u2022") + " ") if kind == "bulletList" else _ordered_marker(list_style, start + index) + " ")
            paragraphs.append("  " * depth + marker + " ".join(part for part in text_parts if part))
            for child in children:
                if child["type"] in {"bulletList", "orderedList"}:
                    list_lines(child, depth + 1)
                elif child["type"] == "table":
                    for row in child.get("content", []):
                        paragraphs.append("  " * (depth + 1) + " | ".join(_plain_inline(cell.get("content", []), assets) for cell in row.get("content", [])))

    for node in nodes:
        kind = node["type"]
        if kind in {"paragraph", "heading", "tableCell"}:
            attrs = node.get("attrs", {})
            paragraphs.extend([""] * min(5, attrs.get("space_before_pt", 0) // 24))
            prefix = "#" * node.get("level", 1) + " " if kind == "heading" else ("## " if attrs.get("style") == "subtitle" else "")
            paragraphs.append(prefix + _plain_inline(node.get("content", []), assets))
            paragraphs.extend([""] * min(5, attrs.get("space_after_pt", 0) // 24))
        elif kind == "image":
            alt = _safe_alt(node.get("attrs", {}).get("alt", ""))
            label = f"[Image: {alt}]" if alt else "[Image]"
            if _asset_bytes(node, assets) is None:
                label = f"[Image unavailable: {alt}]" if alt else "[Image unavailable]"
            before = min(5, node.get("attrs", {}).get("space_before_pt", 0) // 40)
            after = min(5, node.get("attrs", {}).get("space_after_pt", 0) // 40)
            paragraphs.append(("\n" * before) + label + ("\n" * after))
        elif kind in {"bulletList", "orderedList"}:
            list_lines(node)
        elif kind == "table":
            for row in node.get("content", []):
                paragraphs.append("\t".join(_plain_inline(cell.get("content", [])) for cell in row.get("content", [])))
        elif kind == "hardBreak":
            paragraphs.append("\f")
        elif kind == "horizontalRule":
            paragraphs.append("â”€" * 32)
        elif kind in {"doc", "listItem"}:
            paragraphs.extend(_text_paragraphs(node.get("content", []), assets))
    return paragraphs


def plain_text(content, assets=None):
    attrs=content.get("attrs",{})
    lines=[]
    if attrs.get("header"):lines.append(attrs["header"])
    lines.extend(_text_paragraphs(content.get("content", []), assets))
    if attrs.get("footer"):lines.append(attrs["footer"])
    if attrs.get("page_numbers"):lines.append("Page X of Y")
    return "\n\n".join(lines) + "\n"


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

    font_aliases = {"Helvetica":"Arial", "Times-Roman":"Times New Roman", "Courier":"Courier New", "Arimo":"Arial", "Tinos":"Times New Roman", "Cousine":"Courier New", "Carlito":"Calibri", "Caladea":"Cambria"}
    fonts = ["Arial", "Times New Roman", "Courier New", "Calibri", "Cambria", "Roboto", "Open Sans", "Lato", "Montserrat", "Merriweather", "Nunito", "Oswald", "Source Sans 3", "Poppins", "Playfair Display", "Roboto Mono", "Inter", "Arimo", "Tinos", "Cousine", "Carlito", "Caladea", "Noto Sans", "Noto Serif", "Lora", "Raleway", "EB Garamond", "Libre Baskerville", "PT Serif", "Crimson Text"]
    font_ids = {name:index for index,name in enumerate(fonts)}
    colors = []
    def collect(node):
        if isinstance(node, dict):
            for mark in node.get("marks", []):
                if mark.get("type") in {"textColor", "highlight"}:
                    color = mark.get("attrs", {}).get("color")
                    if isinstance(color, str) and color not in colors: colors.append(color)
            for color in (node.get("attrs", {}).get("shading"), node.get("attrs", {}).get("border_color")):
                if isinstance(color, str) and color not in colors: colors.append(color)
            for child in node.get("content", []): collect(child)
        elif isinstance(node, list):
            for child in node: collect(child)
    collect(content)
    color_ids = {color:index+1 for index,color in enumerate(colors)}

    def inline(nodes):
        pieces = []
        for node in nodes:
            kind = node["type"]
            if kind == "text":
                text_value=escape(node.get("text", "")); marks={mark["type"]:mark.get("attrs", {}) for mark in node.get("marks", [])}
                controls=[]
                for name,on,off in (("bold", "\\b ", "\\b0 "), ("italic", "\\i ", "\\i0 "), ("underline", "\\ul ", "\\ulnone "), ("strike", "\\strike ", "\\strike0 "), ("superscript", "\\super ", "\\nosupersub "), ("subscript", "\\sub ", "\\nosupersub ")):
                    if name in marks: controls.append("{"+on+text_value+off+"}");text_value=controls.pop()
                if "fontSize" in marks: text_value="{\\fs"+str(marks["fontSize"]["value"]*2)+" "+text_value+"}"
                if "fontFamily" in marks: text_value="{\\f"+str(font_ids.get(font_aliases.get(marks["fontFamily"]["value"],marks["fontFamily"]["value"]),0))+" "+text_value+"}"
                if "textColor" in marks: text_value="{\\cf"+str(color_ids[marks["textColor"]["color"]])+" "+text_value+"}"
                if "highlight" in marks: text_value="{\\highlight"+str(color_ids[marks["highlight"]["color"]])+" "+text_value+"}"
                if "link" in marks: text_value="{\\field{\\*\\fldinst HYPERLINK \""+escape(marks["link"]["href"])+"\"}{\\fldrslt "+text_value+"}}"
                pieces.append(text_value)
            elif kind == "hardBreak": pieces.append("\\line ")
            elif kind == "image": pieces.append(rtf_image(node))
        return "".join(pieces)

    def blocks(nodes, list_depth=0):
        result = []
        for node in nodes:
            kind = node["type"]
            if kind in {"paragraph", "heading", "tableCell"}:
                attrs = node.get("attrs", {})
                text_value=inline(node.get("content", []))
                if kind == "heading":
                    size=40 if attrs.get("style") == "title" else {1:36,2:30,3:26}.get(node.get("level",1),28)
                    text_value="{\\b\\fs"+str(size)+" "+text_value+"}"
                elif attrs.get("style") == "subtitle": text_value="{\\i\\fs24 "+text_value+"}"
                result.append(f"\\sb{attrs.get('space_before_pt', 0) * 20}\\sa{attrs.get('space_after_pt', 0) * 20}" + text_value)
            elif kind == "image":
                result.append(rtf_image(node))
            elif kind in {"doc", "listItem"}:
                result.extend(blocks(node.get("content", []), list_depth))
            elif kind in {"bulletList", "orderedList"}:
                start = node.get("attrs", {}).get("start", 1)
                checklist = kind == "bulletList" and node.get("attrs", {}).get("list_style") == "checklist"
                for index, item in enumerate(node.get("content", [])):
                    list_style = node.get("attrs", {}).get("list_style", "decimal" if kind == "orderedList" else "disc")
                    marker = "[ ] " if checklist else (({"disc":"\u2022", "circle":"\u25e6", "square":"\u25aa"}.get(list_style, "\u2022") + " ") if kind == "bulletList" else _ordered_marker(list_style, start + index) + " ")
                    item_nodes = item.get("content", [])
                    paragraphs = [child for child in item_nodes if child["type"] in {"paragraph", "heading"}]
                    text = " ".join(inline(child.get("content", [])) for child in paragraphs)
                    result.append(f"\\li{720 * (list_depth + 1)}\\fi-360\\tx{720 * (list_depth + 1)}" + escape(marker + text))
                    result.extend(blocks([child for child in item_nodes if child["type"] in {"bulletList", "orderedList", "table"}], list_depth + 1))
            elif kind == "table":
                table_attrs = node.get("attrs", {})
                width = round(9360 * table_attrs.get("width_percent", 100) / 100)
                columns = _table_columns(node)
                edges = []
                total = 0
                for col in columns:
                    total += round(width * col / 100)
                    edges.append(total)
                for row in node.get("content", []):
                    row_cells = row.get("content", [])
                    row_width = width
                    row_controls = f"\\trowd\\trleft0\\trkeep\\trwWidth{row_width}"
                    column_offset = 0
                    for index, cell in enumerate(row_cells):
                        cell_attrs = cell.get("attrs", {})
                        shading = color_ids.get(cell_attrs.get("shading"), 0)
                        col_span = cell_attrs.get("colspan", 1)
                        edge_index = min(column_offset + col_span - 1, len(edges)-1)
                        border_color = color_ids.get(table_attrs.get("border_color", "#B7C0CC"), 0)
                        row_controls += (f"\\clbrdrt\\brdrs\\brdrw{table_attrs.get('border_width',1)*10}"
                                         f"\\clbrdrcf{border_color}"
                                         f"\\clbrdrl\\brdrs\\brdrw{table_attrs.get('border_width',1)*10}"
                                         f"\\clbrdrcf{border_color}"
                                         f"\\clbrdrb\\brdrs\\brdrw{table_attrs.get('border_width',1)*10}"
                                         f"\\clbrdrcf{border_color}"
                                         f"\\clbrdrr\\brdrs\\brdrw{table_attrs.get('border_width',1)*10}"
                                         f"\\clbrdrcf{border_color}"
                                         + (f"\\clcbpat{shading}" if shading else "")
                                         + f"\\cellx{edges[edge_index]}")
                        column_offset += col_span
                    result.append(row_controls + " " + "".join(inline(cell.get("content", [])) + "\\cell " for cell in row_cells) + "\\row")
            elif kind == "hardBreak": result.append("\\page ")
            elif kind == "horizontalRule": result.append(escape("\u2014" * 32))
        return result

    body = "\\par\n".join(blocks(content.get("content", [])))
    attrs=content.get("attrs",{})
    if attrs.get("header"):body+="{\\header\\pard "+escape(attrs["header"])+"\\par}"
    if attrs.get("footer") or attrs.get("page_numbers"):
        footer=escape(attrs.get("footer",""))
        if attrs.get("page_numbers"):
            footer+=("\\tab " if footer else "")+"Page \\chpgn of {\\field{\\*\\fldinst NUMPAGES}{\\fldrslt 1}}"
        body+="{\\footer\\pard "+footer+"\\par}"
    font_table="{\\fonttbl"+"".join(f"{{\\f{i} {escape(name)};}}" for i,name in enumerate(fonts))+"}"
    color_table="{\\colortbl;"+"".join(f"\\red{int(color[1:3],16)}\\green{int(color[3:5],16)}\\blue{int(color[5:7],16)};" for color in colors)+"}"
    output = ("{\\rtf1\\ansi\\deff0"+font_table+color_table+"\\viewkind4\\uc1\n" + body + "}").encode("ascii")
    _validate_rtf(output)
    return output


def _validate_rtf(data):
    if not isinstance(data, bytes) or len(data) > 25 * 1024 * 1024 or not data.startswith(b"{\\rtf1"):
        raise ValueError("Invalid RTF document")
    allowed = {b"rtf", b"ansi", b"deff", b"fonttbl", b"colortbl", b"red", b"green", b"blue", b"cf", b"highlight", b"f", b"fs", b"b", b"i", b"ul", b"ulnone", b"strike", b"strike0", b"super", b"sub", b"nosupersub", b"field", b"fldinst", b"fldrslt", b"viewkind", b"uc", b"pard", b"par", b"line", b"tab", b"u", b"sb", b"sa", b"li", b"fi", b"tx", b"ql", b"qc", b"qr", b"pict", b"pngblip", b"jpegblip", b"picw", b"pich", b"picwgoal", b"pichgoal", b"trowd", b"trleft", b"trkeep", b"trwwidth", b"clbrdrt", b"clbrdrl", b"clbrdrb", b"clbrdrr", b"clbrdrcf", b"brdrs", b"brdrw", b"clcbpat", b"cellx", b"cell", b"row", b"header", b"footer", b"chpgn", b"page", b"numpages"}
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


def _docx_run(parent, text, marks=(), link_rels=None, link_counter=None):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    relationship_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    types = {mark["type"]: mark.get("attrs", {}) for mark in marks}
    run_parent = parent
    if "link" in types and link_rels is not None and link_counter is not None:
        link_counter[0] += 1
        rid = f"rIdLink{link_counter[0]}"
        link_rels.append((rid, types["link"]["href"]))
        run_parent = ET.SubElement(parent, f"{{{w}}}hyperlink", {f"{{{relationship_ns}}}id": rid})
    run = ET.SubElement(run_parent, f"{{{w}}}r")
    props = ET.SubElement(run, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rPr")
    for name, tag in (("bold", "b"), ("italic", "i"), ("underline", "u"), ("strike", "strike"), ("superscript", "vertAlign"), ("subscript", "vertAlign")):
        if name in types:
            attrs = {"{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val": "single"} if name == "underline" else ({"{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val": "superscript" if name == "superscript" else "subscript"} if name in {"superscript", "subscript"} else {})
            ET.SubElement(props, f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}{tag}", attrs)
    if "fontSize" in types:
        size = str(types["fontSize"]["value"] * 2)
        ET.SubElement(props, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}sz", {"{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val": size})
    if "fontFamily" in types:
        font = types["fontFamily"]["value"]
        font = {"Helvetica": "Arial", "Times-Roman": "Times New Roman", "Courier": "Courier New", "Arimo":"Arial", "Tinos":"Times New Roman", "Cousine":"Courier New", "Carlito":"Calibri", "Caladea":"Cambria"}.get(font, font)
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


def _docx_paragraph(parent, node=None, prefix="", assets=None, media=None, image_rels=None, counter=None, num_id=None, level=0, link_rels=None, link_counter=None):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    para = ET.SubElement(parent, f"{{{w}}}p")
    if node:
        attrs = node.get("attrs", {})
        props = ET.SubElement(para, f"{{{w}}}pPr")
        if node["type"] == "heading":
            ET.SubElement(props, f"{{{w}}}pStyle", {f"{{{w}}}val": "Title" if attrs.get("style") == "title" else f"Heading{node['level']}"})
        elif attrs.get("style") == "subtitle":
            ET.SubElement(props, f"{{{w}}}pStyle", {f"{{{w}}}val": "Subtitle"})
        if attrs.get("align"):
            ET.SubElement(props, f"{{{w}}}jc", {f"{{{w}}}val": {"justify": "both"}.get(attrs["align"], attrs["align"])})
        ind = {}
        left_cm = attrs.get("left_indent_cm", attrs.get("indent", 0) * 1.27)
        if left_cm:
            ind[f"{{{w}}}left"] = str(round(left_cm * 567))
        if attrs.get("right_indent_cm"):
            ind[f"{{{w}}}right"] = str(round(attrs["right_indent_cm"] * 567))
        if attrs.get("first_line_indent_cm"):
            ind[f"{{{w}}}firstLine"] = str(round(attrs["first_line_indent_cm"] * 567))
        if ind:
            ET.SubElement(props, f"{{{w}}}ind", ind)
        if attrs.get("line_spacing"):
            line = {"single": "240", "1.15": "276", "1.5": "360", "double": "480"}[attrs["line_spacing"]]
            ET.SubElement(props, f"{{{w}}}spacing", {f"{{{w}}}line": line, f"{{{w}}}lineRule": "auto"})
        if attrs.get("space_before_pt") or attrs.get("space_after_pt"):
            spacing = props.find(f"{{{w}}}spacing")
            if spacing is None:
                spacing = ET.SubElement(props, f"{{{w}}}spacing")
            spacing.set(f"{{{w}}}before", str(attrs.get("space_before_pt", 0) * 20))
            spacing.set(f"{{{w}}}after", str(attrs.get("space_after_pt", 0) * 20))
        if num_id is not None:
            num_pr = ET.SubElement(props, f"{{{w}}}numPr")
            ET.SubElement(num_pr, f"{{{w}}}ilvl", {f"{{{w}}}val": str(level)})
            ET.SubElement(num_pr, f"{{{w}}}numId", {f"{{{w}}}val": str(num_id)})
        if len(props) == 0:
            para.remove(props)
        if prefix:
            _docx_run(para, prefix, link_rels=link_rels, link_counter=link_counter)
        for child in node.get("content", []):
            if child["type"] == "text":
                _docx_run(para, child.get("text", ""), child.get("marks", []), link_rels, link_counter)
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


def _docx_blocks(parent, nodes, assets=None, media=None, image_rels=None, counter=None, numbering=None, level=0, link_rels=None, link_counter=None):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    for node in nodes:
        kind = node["type"]
        if kind in {"paragraph", "heading"}:
            _docx_paragraph(parent, node, assets=assets, media=media, image_rels=image_rels, counter=counter, link_rels=link_rels, link_counter=link_counter)
        elif kind in {"bulletList", "orderedList"}:
            checklist = kind == "bulletList" and node.get("attrs", {}).get("list_style") == "checklist"
            list_style = node.get("attrs", {}).get("list_style", "decimal" if kind == "orderedList" else "disc")
            list_kind = "checklist" if checklist else (f"ordered:{list_style}" if kind == "orderedList" else f"bullet:{list_style}")
            num_id = _docx_new_num(numbering, list_kind, node.get("attrs", {}).get("start"), level=level)
            for item in node.get("content", []):
                children = item.get("content", [])
                first_paragraph = next((index for index, child in enumerate(children) if child["type"] in {"paragraph", "heading"}), None)
                if first_paragraph is None:
                    _docx_paragraph(parent, {"type": "paragraph", "content": []}, assets=assets, media=media, image_rels=image_rels, counter=counter, num_id=num_id, level=level, link_rels=link_rels, link_counter=link_counter)
                for index, child in enumerate(children):
                    if child["type"] in {"paragraph", "heading"}:
                        _docx_paragraph(parent, child, assets=assets, media=media, image_rels=image_rels, counter=counter, link_rels=link_rels, link_counter=link_counter,
                                        num_id=num_id if index == first_paragraph else None,
                                        level=level)
                    elif child["type"] in {"bulletList", "orderedList"}:
                        _docx_blocks(parent, [child], assets, media, image_rels, counter, numbering, level + 1, link_rels, link_counter)
                    elif child["type"] == "table":
                        _docx_blocks(parent, [child], assets, media, image_rels, counter, numbering, level, link_rels, link_counter)
        elif kind == "table":
            table = ET.SubElement(parent, f"{{{w}}}tbl")
            props = ET.SubElement(table, f"{{{w}}}tblPr")
            width_pct = node.get("attrs", {}).get("width_percent", 100)
            ET.SubElement(props, f"{{{w}}}tblW", {f"{{{w}}}w": str(width_pct * 50), f"{{{w}}}type": "pct"})
            ET.SubElement(props, f"{{{w}}}tblLayout", {f"{{{w}}}type": "fixed"})
            columns = _table_columns(node)
            grid_widths = [round(9360 * width_pct / 100 * width / 100) for width in columns]
            grid = ET.SubElement(table, f"{{{w}}}tblGrid")
            for col_width in grid_widths:
                ET.SubElement(grid, f"{{{w}}}gridCol", {f"{{{w}}}w": str(col_width)})
            borders = ET.SubElement(props, f"{{{w}}}tblBorders")
            border_color = node.get("attrs", {}).get("border_color", "#B7C0CC").lstrip("#")
            border_size = str(max(0, node.get("attrs", {}).get("border_width", 1)) * 4)
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                ET.SubElement(borders, f"{{{w}}}{edge}", {f"{{{w}}}val": "nil" if border_size == "0" else "single", f"{{{w}}}sz": border_size, f"{{{w}}}color": border_color})
            for row in node.get("content", []):
                tr = ET.SubElement(table, f"{{{w}}}tr")
                column_offset = 0
                for cell_index, cell in enumerate(row.get("content", [])):
                    tc = ET.SubElement(tr, f"{{{w}}}tc")
                    cell_props = ET.SubElement(tc, f"{{{w}}}tcPr")
                    col_span = cell.get("attrs", {}).get("colspan", 1)
                    cell_width = sum(grid_widths[column_offset:column_offset + col_span])
                    ET.SubElement(cell_props, f"{{{w}}}tcW", {f"{{{w}}}w": str(cell_width), f"{{{w}}}type": "dxa"})
                    if col_span > 1:
                        ET.SubElement(cell_props, f"{{{w}}}gridSpan", {f"{{{w}}}val": str(col_span)})
                    if cell.get("attrs", {}).get("rowspan", 1) > 1:
                        ET.SubElement(cell_props, f"{{{w}}}vMerge", {f"{{{w}}}val": "restart"})
                    if cell.get("attrs", {}).get("shading"):
                        ET.SubElement(cell_props, f"{{{w}}}shd", {f"{{{w}}}fill": cell["attrs"]["shading"].lstrip("#")})
                    _docx_paragraph(tc, {"type":"paragraph", "content":cell.get("content", [])}, assets=assets, media=media, image_rels=image_rels, counter=counter, link_rels=link_rels, link_counter=link_counter)
                    column_offset += col_span
        elif kind == "hardBreak":
            p = ET.SubElement(parent, f"{{{w}}}p")
            run = ET.SubElement(p, f"{{{w}}}r")
            ET.SubElement(run, f"{{{w}}}br", {f"{{{w}}}type": "page"})
        elif kind == "horizontalRule":
            _docx_paragraph(parent, {"type": "paragraph", "content": [{"type": "text", "text": "â”€" * 32}]}, link_rels=link_rels, link_counter=link_counter)
        elif kind == "image":
            alt = node.get("attrs", {}).get("alt", "")
            _docx_paragraph(parent, {"type": "paragraph", "attrs":node.get("attrs", {}), "content": [{"type": "image", "attrs":node.get("attrs", {})}]}, assets=assets, media=media, image_rels=image_rels, counter=counter, link_rels=link_rels, link_counter=link_counter)


def _docx_new_num(numbering, list_kind, start=None, level=0):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    numbering["next_num"] += 1
    num_id = numbering["next_num"]
    num = ET.SubElement(numbering["root"], f"{{{w}}}num", {f"{{{w}}}numId": str(num_id)})
    ET.SubElement(num, f"{{{w}}}abstractNumId", {f"{{{w}}}val": str(numbering["abstract"][list_kind])})
    if start is not None:
        override = ET.SubElement(num, f"{{{w}}}lvlOverride", {f"{{{w}}}ilvl": str(level)})
        ET.SubElement(override, f"{{{w}}}startOverride", {f"{{{w}}}val": str(start)})
    return num_id


def _docx_numbering():
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    root = ET.Element(f"{{{w}}}numbering")
    definitions = {
        "checklist": ("bullet", "\u2610"),
        "bullet:disc": ("bullet", "\u2022"), "bullet:circle": ("bullet", "\u25e6"), "bullet:square": ("bullet", "\u25aa"),
        "ordered:decimal": ("decimal", None), "ordered:lower-alpha": ("lowerLetter", None),
        "ordered:upper-alpha": ("upperLetter", None), "ordered:lower-roman": ("lowerRoman", None),
        "ordered:upper-roman": ("upperRoman", None),
    }
    abstract = {}
    for abstract_id, (name, (fmt, bullet)) in enumerate(definitions.items(), 1):
        abstract[name] = abstract_id
        item = ET.SubElement(root, f"{{{w}}}abstractNum", {f"{{{w}}}abstractNumId": str(abstract_id)})
        ET.SubElement(item, f"{{{w}}}multiLevelType", {f"{{{w}}}val": "multilevel"})
        for level in range(9):
            lvl = ET.SubElement(item, f"{{{w}}}lvl", {f"{{{w}}}ilvl": str(level)})
            ET.SubElement(lvl, f"{{{w}}}start", {f"{{{w}}}val": "1"})
            ET.SubElement(lvl, f"{{{w}}}numFmt", {f"{{{w}}}val": fmt})
            text = f"%{level + 1}." if bullet is None else bullet
            ET.SubElement(lvl, f"{{{w}}}lvlText", {f"{{{w}}}val": text})
            ET.SubElement(lvl, f"{{{w}}}lvlJc", {f"{{{w}}}val": "left"})
            ppr = ET.SubElement(lvl, f"{{{w}}}pPr")
            tabs = ET.SubElement(ppr, f"{{{w}}}tabs")
            ET.SubElement(tabs, f"{{{w}}}tab", {f"{{{w}}}val": "num", f"{{{w}}}pos": str((level + 1) * 720)})
            ET.SubElement(ppr, f"{{{w}}}ind", {f"{{{w}}}left": str((level + 1) * 720), f"{{{w}}}hanging": "360"})
            if fmt == "bullet":
                rpr = ET.SubElement(lvl, f"{{{w}}}rPr")
                ET.SubElement(rpr, f"{{{w}}}rFonts", {f"{{{w}}}ascii": "Segoe UI Symbol", f"{{{w}}}hAnsi": "Segoe UI Symbol"})
    abstract["checklist"] = abstract.pop("checklist")
    abstract["decimal"] = abstract["ordered:decimal"]
    abstract["bullet"] = abstract["bullet:disc"]
    return {"root": root, "abstract": abstract, "next_num": 0}


def docx(content, assets=None):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    for prefix, namespace in (("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"), ("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"), ("a", "http://schemas.openxmlformats.org/drawingml/2006/main"), ("pic", "http://schemas.openxmlformats.org/drawingml/2006/picture")):
        ET.register_namespace(prefix, namespace)
    ET.register_namespace("w", w)
    root = ET.Element(f"{{{w}}}document")
    body = ET.SubElement(root, f"{{{w}}}body")
    media, image_rels, link_rels, counter, link_counter = {}, [], [], [0], [0]
    numbering = _docx_numbering()
    _docx_blocks(body, content.get("content", []), assets, media, image_rels, counter, numbering, link_rels=link_rels, link_counter=link_counter)
    page_size, orientation, margins, page_dimensions = _layout_attrs(content)
    sect = ET.SubElement(body, f"{{{w}}}sectPr")
    attrs=content.get("attrs",{})
    if attrs.get("header"):
        ET.SubElement(sect,f"{{{w}}}headerReference",{f"{{{w}}}type":"default","{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id":"rIdHeader"})
    if attrs.get("footer") or attrs.get("page_numbers"):
        ET.SubElement(sect,f"{{{w}}}footerReference",{f"{{{w}}}type":"default","{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id":"rIdFooter"})
    width, height = page_dimensions
    size_attrs = {f"{{{w}}}w": str(width), f"{{{w}}}h": str(height)}
    if orientation == "landscape":
        size_attrs[f"{{{w}}}orient"] = "landscape"
    ET.SubElement(sect, f"{{{w}}}pgSz", size_attrs)
    margin_attrs = {f"{{{w}}}{edge}": str(round(margins[f"{edge}_cm"] * 567)) for edge in ("top", "right", "bottom", "left")}
    margin_attrs.update({f"{{{w}}}header": "720", f"{{{w}}}footer": "720", f"{{{w}}}gutter": "0"})
    ET.SubElement(sect, f"{{{w}}}pgMar", margin_attrs)
    content_types = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Default Extension="jpeg" ContentType="image/jpeg"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'''
    rels = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    styles = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="20"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:rPr><w:i/><w:sz w:val="24"/></w:rPr></w:style></w:styles>'''
    content_types = content_types.replace(b"</Types>", b'<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    content_types = content_types.replace(b"</Types>", b'<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>')
    rel_items = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>']
    rel_items.append('<Relationship Id="rIdNumbering" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>')
    header_xml=footer_xml=None
    if attrs.get("header"):
        content_types=content_types.replace(b"</Types>",b'<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/></Types>')
        rel_items.append('<Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>')
        header=ET.Element(f"{{{w}}}hdr")
        _docx_paragraph(header,{"type":"paragraph","content":[{"type":"text","text":attrs["header"]}]})
        header_xml=ET.tostring(header,encoding="utf-8",xml_declaration=True)
    if attrs.get("footer") or attrs.get("page_numbers"):
        content_types=content_types.replace(b"</Types>",b'<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>')
        rel_items.append('<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>')
        footer=ET.Element(f"{{{w}}}ftr")
        p=ET.SubElement(footer,f"{{{w}}}p")
        if attrs.get("footer"):_docx_run(p,attrs["footer"])
        if attrs.get("page_numbers"):
            if attrs.get("footer"):_docx_run(p," Â· ")
            for field in ("PAGE","NUMPAGES"):
                if field=="NUMPAGES":_docx_run(p," of ")
                run=ET.SubElement(p,f"{{{w}}}r")
                ET.SubElement(run,f"{{{w}}}fldChar",{f"{{{w}}}fldCharType":"begin"})
                run=ET.SubElement(p,f"{{{w}}}r")
                instr=ET.SubElement(run,f"{{{w}}}instrText",{"{http://www.w3.org/XML/1998/namespace}space":"preserve"});instr.text=f" {field} "
                run=ET.SubElement(p,f"{{{w}}}r");ET.SubElement(run,f"{{{w}}}fldChar",{f"{{{w}}}fldCharType":"separate"})
                placeholder=ET.SubElement(ET.SubElement(p,f"{{{w}}}r"),f"{{{w}}}t");placeholder.text="1"
                run=ET.SubElement(p,f"{{{w}}}r");ET.SubElement(run,f"{{{w}}}fldChar",{f"{{{w}}}fldCharType":"end"})
        footer_xml=ET.tostring(footer,encoding="utf-8",xml_declaration=True)
    rel_items.extend(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{target}"/>' for rid, target in image_rels)
    rel_items.extend(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{html.escape(target, quote=True)}" TargetMode="External"/>' for rid, target in link_rels)
    word_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rel_items) + "</Relationships>").encode("utf-8")
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/styles.xml", styles)
        archive.writestr("word/numbering.xml", ET.tostring(numbering["root"], encoding="utf-8", xml_declaration=True))
        archive.writestr("word/_rels/document.xml.rels", word_rels)
        if header_xml:archive.writestr("word/header1.xml",header_xml)
        if footer_xml:archive.writestr("word/footer1.xml",footer_xml)
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
    list_style_names = {}
    list_specs = {
        "bullet:disc": ("bullet", "\u2022"), "bullet:circle": ("bullet", "\u25e6"), "bullet:square": ("bullet", "\u25aa"), "bullet:checklist": ("bullet", "\u2610"),
        "ordered:decimal": ("1", None), "ordered:lower-alpha": ("a", None), "ordered:upper-alpha": ("A", None), "ordered:lower-roman": ("i", None), "ordered:upper-roman": ("I", None),
    }
    for key, (fmt, glyph) in list_specs.items():
        style_name = "DigiDoc" + key.replace(":", "_").replace("-", "_")
        list_style_names[key] = style_name
        style = ET.SubElement(automatic, f"{{{ns['text']}}}list-style", {f"{{{ns['style']}}}name": style_name})
        for level in range(1, 10):
            if glyph is None:
                ET.SubElement(style, f"{{{ns['text']}}}list-level-style-number", {f"{{{ns['text']}}}level": str(level), f"{{{ns['style']}}}num-format": fmt, f"{{{ns['style']}}}num-suffix": ".", f"{{{ns['text']}}}start-value": "1"})
            else:
                ET.SubElement(style, f"{{{ns['text']}}}list-level-style-bullet", {f"{{{ns['text']}}}level": str(level), f"{{{ns['text']}}}bullet-char": glyph})
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
            parent_style = ("Title" if attrs.get("style") == "title" else f"Heading {node['level']}" if kind == "heading" else "Subtitle" if attrs.get("style") == "subtitle" else "Normal")
            style_attrs = {f"{{{ns['style']}}}name": style_name, f"{{{ns['style']}}}family": "paragraph", f"{{{ns['style']}}}parent-style-name": parent_style}
            style = ET.SubElement(automatic, f"{{{ns['style']}}}style", style_attrs)
            prop = {}
            if attrs.get("align"):
                prop[f"{{{ns['fo']}}}text-align"] = attrs["align"]
            left_cm = attrs.get("left_indent_cm", attrs.get("indent", 0) * 1.27)
            if left_cm:
                prop[f"{{{ns['fo']}}}margin-left"] = f"{left_cm:.2f}cm"
            if attrs.get("right_indent_cm"):
                prop[f"{{{ns['fo']}}}margin-right"] = f"{attrs['right_indent_cm']:.2f}cm"
            if attrs.get("first_line_indent_cm"):
                prop[f"{{{ns['fo']}}}text-indent"] = f"{attrs['first_line_indent_cm']:.2f}cm"
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
                        if "superscript" in marks: text_props[f"{{{ns['style']}}}text-position"] = "super 58%"
                        if "subscript" in marks: text_props[f"{{{ns['style']}}}text-position"] = "sub 58%"
                        if "textColor" in marks: text_props[f"{{{ns['fo']}}}color"] = marks["textColor"]["color"]
                        if "highlight" in marks: text_props[f"{{{ns['fo']}}}background-color"] = marks["highlight"]["color"]
                        if "fontSize" in marks: text_props[f"{{{ns['fo']}}}font-size"] = f"{marks['fontSize']['value']}pt"
                        if "fontFamily" in marks: text_props[f"{{{ns['fo']}}}font-family"] = {"Helvetica": "Arial", "Times-Roman": "Times New Roman", "Courier": "Courier New", "Arimo":"Arial", "Tinos":"Times New Roman", "Cousine":"Courier New", "Carlito":"Calibri", "Caladea":"Cambria"}.get(marks["fontFamily"]["value"], marks["fontFamily"]["value"])
                        ET.SubElement(span_style, f"{{{ns['style']}}}text-properties", text_props)
                        span_parent = element
                        if "link" in marks:
                            span_parent = ET.SubElement(element, f"{{{ns['text']}}}a", {f"{{{ns['xlink']}}}href": marks["link"]["href"]})
                        span = ET.SubElement(span_parent, f"{{{ns['text']}}}span", {f"{{{ns['text']}}}style-name": span_name})
                        span.text = child.get("text", "")
                    else:
                        text_parent = element
                        if "link" in marks:
                            text_parent = ET.SubElement(element, f"{{{ns['text']}}}a", {f"{{{ns['xlink']}}}href": marks["link"]["href"]})
                        text_node = ET.SubElement(text_parent, f"{{{ns['text']}}}span")
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

    def blocks(parent, nodes, list_level=0):
        for node in nodes:
            kind = node["type"]
            if kind in {"paragraph", "heading"}:
                para(parent, node)
            elif kind in {"bulletList", "orderedList"}:
                checklist = kind == "bulletList" and node.get("attrs", {}).get("list_style") == "checklist"
                list_style = node.get("attrs", {}).get("list_style", "decimal" if kind == "orderedList" else "disc")
                style_name = list_style_names[("bullet:" if kind == "bulletList" else "ordered:") + list_style]
                list_el = ET.SubElement(parent, f"{{{ns['text']}}}list", {f"{{{ns['text']}}}style-name": style_name})
                for item_index, item in enumerate(node.get("content", [])):
                    item_attrs = {}
                    if kind == "orderedList" and item_index == 0 and node.get("attrs", {}).get("start") is not None:
                        item_attrs[f"{{{ns['text']}}}start-value"] = str(node["attrs"]["start"])
                    li = ET.SubElement(list_el, f"{{{ns['text']}}}list-item", item_attrs)
                    children = item.get("content", [])
                    if children:
                        for child_index, child in enumerate(children):
                            if child["type"] in {"paragraph", "heading"}:
                                para(li, child, "[ ] " if checklist and child_index == 0 else "")
                            else:
                                blocks(li, [child], list_level + 1)
                    else:
                        para(li, prefix="[ ] " if checklist else "")
            elif kind == "table":
                table_index = sum(1 for child in parent if child.tag == f"{{{ns['table']}}}table") + 1
                table_style_name = f"DigiDocTable{table_index}"
                table_style = ET.SubElement(automatic, f"{{{ns['style']}}}style", {f"{{{ns['style']}}}name": table_style_name, f"{{{ns['style']}}}family": "table"})
                _page_size, _orientation, margins, page_twips = _layout_attrs(content)
                page_width_cm = page_twips[0] / 567
                content_width_cm = page_width_cm - margins["left_cm"] - margins["right_cm"]
                table_width_cm = content_width_cm * node.get("attrs", {}).get("width_percent", 100) / 100
                ET.SubElement(table_style, f"{{{ns['style']}}}table-properties", {f"{{{ns['style']}}}width": f"{table_width_cm:.2f}cm"})
                table_el = ET.SubElement(parent, f"{{{ns['table']}}}table", {f"{{{ns['table']}}}name": f"Table{table_index}", f"{{{ns['table']}}}style-name": table_style_name})
                table_columns = _table_columns(node)
                for column_index, column_width in enumerate(table_columns, 1):
                    column_style_name = f"{table_style_name}Column{column_index}"
                    column_style = ET.SubElement(automatic, f"{{{ns['style']}}}style", {f"{{{ns['style']}}}name": column_style_name, f"{{{ns['style']}}}family": "table-column"})
                    ET.SubElement(column_style, f"{{{ns['style']}}}table-column-properties", {f"{{{ns['style']}}}column-width": f"{table_width_cm * column_width / 100:.2f}cm"})
                    ET.SubElement(table_el, f"{{{ns['table']}}}table-column", {f"{{{ns['table']}}}style-name": column_style_name})
                for row in node.get("content", []):
                    row_el = ET.SubElement(table_el, f"{{{ns['table']}}}table-row")
                    for cell in row.get("content", []):
                        cell_el = ET.SubElement(row_el, f"{{{ns['table']}}}table-cell")
                        if cell.get("attrs", {}).get("colspan", 1) > 1:
                            cell_el.set(f"{{{ns['table']}}}number-columns-spanned", str(cell["attrs"]["colspan"]))
                        if cell.get("attrs", {}).get("rowspan", 1) > 1:
                            cell_el.set(f"{{{ns['table']}}}number-rows-spanned", str(cell["attrs"]["rowspan"]))
                        cell_style_name = f"{table_style_name}Cell{len(automatic)}"
                        cell_style = ET.SubElement(automatic, f"{{{ns['style']}}}style", {f"{{{ns['style']}}}name": cell_style_name, f"{{{ns['style']}}}family": "table-cell"})
                        border_width = node.get("attrs", {}).get("border_width", 1)
                        border_color = node.get("attrs", {}).get("border_color", "#B7C0CC")
                        border = f"{max(0.5, border_width * 0.75):g}pt solid {border_color}" if border_width else "none"
                        cell_props = {f"{{{ns['fo']}}}border": border, f"{{{ns['fo']}}}padding": "0.12cm"}
                        if cell.get("attrs", {}).get("shading"):
                            cell_props[f"{{{ns['fo']}}}background-color"] = cell["attrs"]["shading"]
                        ET.SubElement(cell_style, f"{{{ns['style']}}}table-cell-properties", cell_props)
                        cell_el.set(f"{{{ns['table']}}}style-name", cell_style_name)
                        para(cell_el, {"type": "paragraph", "content": cell.get("content", [])})
            elif kind == "hardBreak":
                para(parent, {"type": "paragraph", "content": [{"type": "text", "text": ""}]})
            elif kind == "horizontalRule":
                para(parent, {"type": "paragraph", "content": [{"type": "text", "text": "â”€" * 32}]})
            elif kind == "image":
                para(parent, {"type": "paragraph", "attrs":node.get("attrs", {}), "content": [node]})

    blocks(text_body, content.get("content", []))
    styles_root = ET.Element(f"{{{ns['office']}}}document-styles", {f"{{{ns['office']}}}version": "1.3"})
    common_styles = ET.SubElement(styles_root, f"{{{ns['office']}}}styles")
    default_style = ET.SubElement(common_styles, f"{{{ns['style']}}}default-style", {f"{{{ns['style']}}}family": "paragraph"})
    ET.SubElement(default_style, f"{{{ns['style']}}}paragraph-properties", {f"{{{ns['fo']}}}margin-top": "0in", f"{{{ns['fo']}}}margin-bottom": "0.08in"})
    ET.SubElement(default_style, f"{{{ns['style']}}}text-properties", {f"{{{ns['fo']}}}font-family": "Arial", f"{{{ns['fo']}}}font-size": "10pt"})
    for name,size,bold,italic in (("Normal",10,False,False),("Title",20,True,False),("Subtitle",12,False,True),("Heading 1",18,True,False),("Heading 2",15,True,False),("Heading 3",13,True,False)):
        style=ET.SubElement(common_styles,f"{{{ns['style']}}}style",{f"{{{ns['style']}}}name":name,f"{{{ns['style']}}}family":"paragraph"})
        props={f"{{{ns['fo']}}}font-size":f"{size}pt"}
        if bold: props[f"{{{ns['fo']}}}font-weight"]="bold"
        if italic: props[f"{{{ns['fo']}}}font-style"]="italic"
        ET.SubElement(style,f"{{{ns['style']}}}text-properties",props)
    _size, orientation, margins, page_twips = _layout_attrs(content)
    page_width, page_height = page_twips
    page_width_cm, page_height_cm = page_width / 567, page_height / 567
    automatic_styles = ET.SubElement(styles_root, f"{{{ns['office']}}}automatic-styles")
    page_layout = ET.SubElement(automatic_styles, f"{{{ns['style']}}}page-layout", {f"{{{ns['style']}}}name": "pm1"})
    ET.SubElement(page_layout, f"{{{ns['style']}}}page-layout-properties", {
        f"{{{ns['fo']}}}page-width": f"{page_width_cm:.2f}cm",
        f"{{{ns['fo']}}}page-height": f"{page_height_cm:.2f}cm",
        f"{{{ns['style']}}}print-orientation": orientation,
        f"{{{ns['fo']}}}margin-top": f"{margins['top_cm']:.2f}cm",
        f"{{{ns['fo']}}}margin-right": f"{margins['right_cm']:.2f}cm",
        f"{{{ns['fo']}}}margin-bottom": f"{margins['bottom_cm']:.2f}cm",
        f"{{{ns['fo']}}}margin-left": f"{margins['left_cm']:.2f}cm",
    })
    master_styles = ET.SubElement(styles_root, f"{{{ns['office']}}}master-styles")
    master_page=ET.SubElement(master_styles, f"{{{ns['style']}}}master-page", {
        f"{{{ns['style']}}}name": "Standard", f"{{{ns['style']}}}page-layout-name": "pm1",
    })
    attrs=content.get("attrs",{})
    if attrs.get("header"):
        header=ET.SubElement(master_page,f"{{{ns['style']}}}header")
        ET.SubElement(header,f"{{{ns['text']}}}p").text=attrs["header"]
    if attrs.get("footer") or attrs.get("page_numbers"):
        footer=ET.SubElement(master_page,f"{{{ns['style']}}}footer")
        paragraph=ET.SubElement(footer,f"{{{ns['text']}}}p")
        paragraph.text=attrs.get("footer","")
        if attrs.get("page_numbers"):
            if paragraph.text:paragraph.text+=" Â· "
            ET.SubElement(paragraph,f"{{{ns['text']}}}span").text="Page "
            ET.SubElement(paragraph,f"{{{ns['text']}}}page-number").text="1"
            ET.SubElement(paragraph,f"{{{ns['text']}}}span").text=" of "
            ET.SubElement(paragraph,f"{{{ns['text']}}}page-count").text="1"
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
