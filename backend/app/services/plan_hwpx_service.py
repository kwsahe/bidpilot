"""제안서 · 사업계획서 초안 → HWPX(한글) — 워드 판과 같은 블록(`plan_export_service.document_blocks`)을 OWPML 로 그린다.

11-03 대표 「hwpx 로 사업제안서 작성 · 2번(앱이 직접)」. 9-29 에 사업계획서 HWPX 를 뺀 까닭은 「한컴에서 열리는지 확인할 수 없음」
이었다 — 11-03 노트북의 한글 2024 로 열어 PDF 로 저장해 확인했다(한글 COM 방법은 CLAUDE.md 「2.2.1」).

구조는 한글 2024 가 만든 실제 HWPX(나라장터 공고서)를 따른다: 표 칸마다 cellAddr · cellSpan · cellSz · cellMargin, 첫 문단에
쪽 설정(secPr) · 단(colPr) · 쪽 번호(pageNum). 줄 배치(linesegarray)는 넣지 않는다 — 한글이 열 때 다시 계산한다.
숫자는 워드 판과 같다(SPEC): A4 · 여백 22/20mm · 맑은 고딕 · 본문 11pt · 제목 15 / 12.5pt 남색 · 표 9.5pt · 머리 칸 바탕 · 「(담당자 입력)」
갈색 점선 밑줄. 제출용에는 표식 · 근거 · 메모가 없다(블록 단계에서 이미 빠진다).
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

from app.services import plan_export_service as pe
from app.services.plan_draft_service import SUGGESTION
from app.services.plan_form_service import HUMAN_INPUT, HUMAN_INPUT_RE

MIMETYPE = "application/hwp+zip"
_NS = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": "http://www.idpf.org/2007/opf/",
    "ooxmlchart": "http://www.hancom.co.kr/hwpml/2016/ooxmlchart",
    "hwpunitchar": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
    "epub": "http://www.idpf.org/2007/ops",
    "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
}
_XMLNS = " ".join(f'xmlns:{k}="{v}"' for k, v in _NS.items())
_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
FONT = "맑은 고딕"


def mm(value: float) -> int:
    """mm → HWPUNIT(1/7200 인치)."""
    return round(value * 7200 / 25.4)


def _pt(value: float) -> int:
    """pt → HWPUNIT(글자 크기 · 문단 간격은 1pt = 100)."""
    return round(value * 100)


TEXT_MM = 166.0
#: 「○ 」 · 「- 」 폭 — 워드 판 트윕 값(× 5 = HWPUNIT).
GLYPH, DASH, MEMO = pe.TW_GLYPH * 5, pe.TW_DASH * 5, pe.TW_MEMO * 5

# 글자 모양 — (이름, pt, 색, 굵게, 밑줄 색, 자간 %)
_CHARS: tuple[tuple[str, float, str, bool, str | None, int], ...] = (
    ("body", 11, pe.INK, False, None, 0),
    ("bold", 11, pe.INK, True, None, 0),
    ("h1", 15, pe.NAVY, True, None, 0),
    ("h2", 12.5, pe.NAVY, True, None, 0),
    ("cell", 9.5, pe.INK, False, None, 0),
    ("cell_bold", 9.5, pe.INK, True, None, 0),
    ("table_title", 10, pe.NAVY, True, None, 0),
    ("cover_kind", 26, pe.NAVY, True, None, 30),
    ("cover_notice", 14, pe.INK, True, None, 0),
    ("cover_label", 11, pe.MUTED, False, None, 0),
    ("cover_value", 12, pe.INK, True, None, 0),
    ("ai", 11, pe.AI_INK, False, None, 0),
    ("tag", 8, pe.NAVY, True, None, 0),
    ("small", 8.5, pe.MUTED, False, None, 0),
    ("warn", 12, pe.WARN, True, None, 0),
    ("memo", 10, pe.INK, False, None, 0),
    ("memo_bold", 10, pe.INK, True, None, 0),
    ("blank", 11, pe.BLANK_INK, False, pe.BLANK_LINE, 0),
    ("cell_blank", 9.5, pe.BLANK_INK, False, pe.BLANK_LINE, 0),
    ("grid_mark", 9.5, pe.NAVY, False, None, 0),
    ("grid_head", 6, pe.INK, False, None, -10),
    ("grid_mark_small", 7, pe.NAVY, False, None, 0),
    ("cover_link", 10, pe.LINK_INK, False, pe.LINK_INK, 0),  # 표지 「공고 원문」(2.9.1 · 실선 밑줄)
)
C = {name: i for i, (name, *_rest) in enumerate(_CHARS)}

# 테두리 · 바탕 — (이름, {변: (선, 굵기, 색)}, 바탕색)
_SOLID = "SOLID"
_BORDERS: tuple[tuple[str, dict[str, tuple[str, str, str]], str | None], ...] = (
    ("none", {}, None),
    ("plain", {}, None),
    ("cell", {s: (_SOLID, "0.12 mm", pe.RULE) for s in ("left", "right", "top", "bottom")}, None),
    ("head", {s: (_SOLID, "0.12 mm", pe.RULE) for s in ("left", "right", "top", "bottom")}, pe.HEAD_FILL),
    ("h1", {"bottom": (_SOLID, "0.5 mm", pe.NAVY)}, None),
    ("band", {"top": (_SOLID, "0.4 mm", pe.NAVY), "bottom": (_SOLID, "0.4 mm", pe.NAVY)}, None),
    ("banner", {s: (_SOLID, "0.4 mm", pe.WARN) for s in ("left", "right", "top", "bottom")}, None),
    ("box", {s: (_SOLID, "0.12 mm", pe.RULE) for s in ("left", "right", "top", "bottom")}, pe.BOX_FILL),
)
B = {name: i + 1 for i, (name, *_rest) in enumerate(_BORDERS)}  # id 는 1부터

# 문단 모양 — (이름, 정렬, 왼쪽, 첫 줄(음수 = 내어쓰기), 위 pt, 아래 pt, 줄 간격 %, 다음과 함께, 테두리, 오른쪽)
_PARAS: tuple[tuple[str, str, int, int, float, float, int, bool, str, int], ...] = (
    ("body", "JUSTIFY", 0, 0, 0, 6, 160, False, "plain", 0),
    ("left", "LEFT", 0, 0, 0, 0, 130, False, "plain", 0),
    ("right", "RIGHT", 0, 0, 0, 0, 130, False, "plain", 0),
    ("center", "CENTER", 0, 0, 0, 0, 130, False, "plain", 0),
    ("h1", "LEFT", 0, 0, 22, 4, 150, True, "h1", 0),
    ("h1_top", "LEFT", 0, 0, 0, 4, 150, True, "h1", 0),
    ("h2", "LEFT", 0, 0, 16, 6, 150, True, "plain", 0),
    ("h2_tight", "LEFT", 0, 0, 8, 6, 150, True, "plain", 0),
    ("sub", "LEFT", GLYPH, -GLYPH, 10, 3, 160, True, "plain", 0),
    ("sub_tight", "LEFT", GLYPH, -GLYPH, 0, 3, 160, True, "plain", 0),
    ("item", "LEFT", GLYPH, -GLYPH, 0, 2, 160, False, "plain", 0),
    ("dash", "LEFT", GLYPH + DASH, -DASH, 0, 2, 160, False, "plain", 0),
    ("label", "LEFT", 0, 0, 0, 2, 160, True, "plain", 0),
    ("label_deep", "LEFT", GLYPH, 0, 0, 2, 160, True, "plain", 0),
    ("para_deep", "JUSTIFY", GLYPH, 0, 0, 6, 160, False, "plain", 0),
    ("table_title", "CENTER", 0, 0, 8, 3, 140, True, "plain", 0),
    ("memo", "LEFT", 0, 0, 0, 3, 150, False, "plain", 0),
    ("memo_deep", "LEFT", MEMO, 0, 0, 3, 150, False, "plain", 0),
    ("cover_kind", "CENTER", 0, 0, 150, 34, 130, False, "plain", 0),
    ("cover_band", "CENTER", mm(8), 0, 0, 0, 150, False, "band", mm(8)),
    ("cover_gap", "LEFT", 0, 0, 250, 0, 130, False, "plain", 0),
    ("cover_banner", "CENTER", 0, 0, 28, 0, 130, False, "plain", 0),
    ("cover_gap_link", "LEFT", 0, 0, 250 - 2 * pe.LINK_LINE_PT, 0, 130, False, "plain", 0),  # 표지 「공고 원문」 줄이 있을 때(2.9.1)
)
#: 제목 아래 선 뒤 간격(pt) — 한글은 문단 아래 테두리를 문단 끝에 그려 위 간격 0 인 다음 줄에 붙었다. 「이름+gap」은 위 간격이 이만큼 이상인 판.
RULE_GAP = 8
_PARAS += tuple((f"{name}+gap", align, left, intent, max(prev, RULE_GAP), *rest) for name, align, left, intent, prev, *rest in _PARAS)
P = {name: i for i, (name, *_rest) in enumerate(_PARAS)}


# ---------------------------------------------------------------------------
# 머리 파일(header.xml)
# ---------------------------------------------------------------------------


def _langs(value: str) -> str:
    return " ".join(f'{lang}="{value}"' for lang in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user"))


def _char_pr(i: int, size: float, color: str, bold: bool, underline: str | None, spacing: int, *, solid: bool = False) -> str:
    line = (f'<hh:underline type="BOTTOM" shape="{"SOLID" if solid else "DOT"}" color="#{underline}"/>' if underline
            else '<hh:underline type="NONE" shape="SOLID" color="#000000"/>')
    return (f'<hh:charPr id="{i}" height="{_pt(size)}" textColor="#{color}" shadeColor="none" useFontSpace="0" useKerning="0" '
            f'symMark="NONE" borderFillIDRef="{B["plain"]}"><hh:fontRef {_langs("0")}/><hh:ratio {_langs("100")}/>'
            f'<hh:spacing {_langs(str(spacing))}/><hh:relSz {_langs("100")}/><hh:offset {_langs("0")}/>'
            f'{"<hh:bold/>" if bold else ""}{line}<hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/>'
            '<hh:shadow type="NONE" color="#B2B2B2" offsetX="10" offsetY="10"/></hh:charPr>')


def _border_fill(i: int, sides: dict[str, tuple[str, str, str]], fill: str | None) -> str:
    def side(name: str) -> str:
        kind, width, color = sides.get(name, ("NONE", "0.1 mm", "000000"))
        return f'<hh:{name}Border type="{kind}" width="{width}" color="#{color}"/>'

    brush = (f'<hc:fillBrush><hc:winBrush faceColor="#{fill}" hatchColor="#999999" alpha="0"/></hc:fillBrush>' if fill
             else '<hc:fillBrush><hc:winBrush faceColor="none" hatchColor="#999999" alpha="0"/></hc:fillBrush>')
    return (f'<hh:borderFill id="{i}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
            '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
            f'{side("left")}{side("right")}{side("top")}{side("bottom")}<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
            f"{brush}</hh:borderFill>")


def _para_pr(i: int, align: str, left: int, intent: int, prev: float, after: float, line: int, keep: bool, border: str, right: int) -> str:
    offset = ('offsetLeft="0" offsetRight="0" offsetTop="425" offsetBottom="425"' if border == "band" else
              'offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0"')
    return (f'<hh:paraPr id="{i}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">'
            f'<hh:align horizontal="{align}" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/>'
            f'<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="{int(keep)}" '
            'keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
            f'<hh:margin><hc:intent value="{intent}" unit="HWPUNIT"/><hc:left value="{left}" unit="HWPUNIT"/>'
            f'<hc:right value="{right}" unit="HWPUNIT"/><hc:prev value="{_pt(prev)}" unit="HWPUNIT"/>'
            f'<hc:next value="{_pt(after)}" unit="HWPUNIT"/></hh:margin><hh:lineSpacing type="PERCENT" value="{line}" unit="HWPUNIT"/>'
            f'<hh:border borderFillIDRef="{B[border]}" {offset} connect="0" ignoreMargin="0"/></hh:paraPr>')


def header_xml() -> str:
    fonts = "".join(
        f'<hh:fontface lang="{lang}" fontCnt="1"><hh:font id="0" face="{FONT}" type="TTF" isEmbedded="0">'
        '<hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="4" contrast="0" strokeVariation="1" armStyle="1" '
        'letterform="1" midline="1" xHeight="1"/></hh:font></hh:fontface>'
        for lang in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"))
    borders = "".join(_border_fill(B[name], sides, fill) for name, sides, fill in _BORDERS)
    chars = "".join(_char_pr(C[name], *rest, solid=name == "cover_link") for name, *rest in _CHARS)
    paras = "".join(_para_pr(P[name], *rest) for name, *rest in _PARAS)
    return (f'{_DECL}<hh:head {_XMLNS} version="1.4" secCnt="1">'
            '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/><hh:refList>'
            f'<hh:fontfaces itemCnt="7">{fonts}</hh:fontfaces>'
            f'<hh:borderFills itemCnt="{len(_BORDERS)}">{borders}</hh:borderFills>'
            f'<hh:charProperties itemCnt="{len(_CHARS)}">{chars}</hh:charProperties>'
            '<hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties>'
            '<hh:numberings itemCnt="1"><hh:numbering id="1" start="0"/></hh:numberings>'
            f'<hh:paraProperties itemCnt="{len(_PARAS)}">{paras}</hh:paraProperties>'
            f'<hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="{P["body"]}" '
            f'charPrIDRef="{C["body"]}" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>'
            '</hh:refList><hh:compatibleDocument targetProgram="HWP201X"><hh:layoutCompatibility/></hh:compatibleDocument>'
            '<hh:docOption><hh:linkinfo path="" pageInherit="1" footnoteInherit="0"/></hh:docOption></hh:head>')


# ---------------------------------------------------------------------------
# 본문(section0.xml)
# ---------------------------------------------------------------------------

Run = tuple[str, str]  # (글, 글자 모양 이름)


def _text(value: Any) -> str:
    return escape(pe._clean(value).replace("\r", " ").replace("\n", " ").replace("\t", " "))


def _runs(runs: list[Run]) -> str:
    """글 조각 → run. 빈칸 표시와 변형 꼴(`HUMAN_INPUT_RE` · 2.8.0 B3) 조각은 빈칸 글자 모양(갈색 점선 밑줄) — 글은 그대로."""
    out: list[str] = []
    for text, char in runs:
        if char == "cover_link":
            out.append(_link_runs(str(text)))
            continue
        blank = "cell_blank" if char.startswith("cell") else "blank"
        at = 0
        value = str(text)
        for match in [*HUMAN_INPUT_RE.finditer(value), None]:
            piece = value[at:match.start() if match else len(value)]
            if piece:
                out.append(f'<hp:run charPrIDRef="{C[char]}"><hp:t>{_text(piece)}</hp:t></hp:run>')
            if match:
                out.append(f'<hp:run charPrIDRef="{C[blank]}"><hp:t>{_text(match.group(0))}</hp:t></hp:run>')
                at = match.end()
    return "".join(out) or f'<hp:run charPrIDRef="{C["body"]}"/>'


def _link_runs(url: str) -> str:
    """하이퍼링크 필드 — 한글 2024 가 다시 저장한 꼴(Command = 「:」 · 「?」를 「\\:」 · 「\\?」로 바꾼 주소;1;0;0; · Path = 주소 전체).
    한글은 Command 의 「:」 · 「?」를 구분자로 읽어 PDF 링크에서 「?」 뒤(공고번호 · 차수)가 잘렸다(2.10.0 T7 · 11-13 한글 2024 실측 —
    2.9.1 의 「Path = 주소의 ? 앞」 꼴). 문서에 하나뿐이라 id 고정.
    ponytail: 실측한 이스케이프는 「:」 · 「?」뿐(「=」 · 「&」는 그대로) — 「;」가 든 주소가 생기면 한글로 다시 떠 볼 것(「\\」는 `official_link` 가 거절)."""
    u = escape(url)
    command = u.replace(":", "\\:").replace("?", "\\?")
    cp = C["cover_link"]
    return (f'<hp:run charPrIDRef="{cp}"><hp:ctrl><hp:fieldBegin id="1900000101" type="HYPERLINK" name="" editable="0" dirty="1" '
            'zorder="-1" fieldid="1900000201" metaTag=""><hp:parameters cnt="6" name=""><hp:integerParam name="Prop">0</hp:integerParam>'
            f'<hp:stringParam name="Command">{command};1;0;0;</hp:stringParam><hp:stringParam name="Path">{u}</hp:stringParam>'
            '<hp:stringParam name="Category">HWPHYPERLINK_TYPE_URL</hp:stringParam>'
            '<hp:stringParam name="TargetType">HWPHYPERLINK_TARGET_BOOKMARK</hp:stringParam>'
            '<hp:stringParam name="DocOpenType">HWPHYPERLINK_JUMP_CURRENTTAB</hp:stringParam></hp:parameters></hp:fieldBegin></hp:ctrl></hp:run>'
            f'<hp:run charPrIDRef="{cp}"><hp:t>{u}</hp:t></hp:run>'
            f'<hp:run charPrIDRef="{cp}"><hp:ctrl><hp:fieldEnd beginIDRef="1900000101" fieldid="1900000201"/></hp:ctrl><hp:t/></hp:run>')


def _p(runs: list[Run], para: str, *, page_break: bool = False, ctrl: str = "") -> str:
    head = f'<hp:run charPrIDRef="{C["body"]}">{ctrl}</hp:run>' if ctrl else ""
    return (f'<hp:p id="0" paraPrIDRef="{P[para]}" styleIDRef="0" pageBreak="{int(page_break)}" columnBreak="0" merged="0">'
            f"{head}{_runs(runs)}</hp:p>")


# 떠 있는 긴 표 뒤 빈 문단(2.11.0 T1 · `_Writer.table` 이 넣고 `section_xml` 이 문서 끝에서만 뺀다)
_TABLE_GAP = _p([], "left")


class _Cell:
    def __init__(self, paragraphs: list[tuple[list[Run], str]], *, border: str = "cell", span: int = 1, height_mm: float = 7.0) -> None:
        self.paragraphs, self.border, self.span, self.height = paragraphs, border, span, height_mm


class _Writer:
    """블록 → 문단 · 표 XML. 표 id 는 문서 안에서 하나씩."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.table_id = 1000
        self.page_break = False
        self.prev_kind: str | None = None
        self.after_rule = False  # 바로 앞이 밑줄 제목(h1 · 검토 메모 머리)

    def _gap(self, para: str) -> str:
        para, self.after_rule = (f"{para}+gap" if self.after_rule else para), para.startswith("h1")
        return para

    def para(self, runs: list[Run], para: str, *, ctrl: str = "") -> None:
        self.parts.append(_p(runs, self._gap(para), page_break=self.page_break, ctrl=ctrl))
        self.page_break = False

    def table(self, rows: list[list[_Cell]], widths_mm: list[float], *, header_rows: int = 0, host: str = "left",
              whole: bool = True, side_mm: float = 1.8) -> None:
        """표 — `host` 문단에 붙인다. host 가 가운데 정렬이면 표도 가운데.

        `whole`(작은 표)은 글자처럼 취급(treatAsChar=1)해 통째로 다음 쪽으로 넘긴다 — 떠 있는 표는 쪽 끝에서 쪼개져 표 제목 · 머리줄만
        앞 쪽에 남았다(앞 문단의 「다음과 함께」가 떠 있는 표에는 걸리지 않음 · 11-04 검토). 긴 표는 떠 있게(treatAsChar=0) 두어 행 단위로
        나눈다 — 글자처럼 취급하면 한글이 쪽에서 나누지 못해 쪽 아래로 넘쳤다(11-03). 어느 쪽인지는 워드 판 규칙과 같다(호출하는 곳)."""
        center = _PARAS[P[host]][1] == "CENTER"
        host = self._gap(host)
        widths = [mm(w) for w in widths_mm]
        widths[-1] += mm(sum(widths_mm)) - sum(widths)
        self.table_id += 1
        body: list[str] = []
        height = 0
        for r, row in enumerate(rows):
            col = 0
            cells: list[str] = []
            row_height = mm(max(cell.height for cell in row))
            height += row_height
            for cell in row:
                width = sum(widths[col:col + cell.span])
                inner = "".join(_p(runs, para) for runs, para in cell.paragraphs) or _p([], "left")
                cells.append(
                    f'<hp:tc name="" header="{int(r < header_rows)}" hasMargin="1" protect="0" editable="0" dirty="0" '
                    f'borderFillIDRef="{B[cell.border]}"><hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
                    'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                    f'{inner}</hp:subList><hp:cellAddr colAddr="{col}" rowAddr="{r}"/><hp:cellSpan colSpan="{cell.span}" rowSpan="1"/>'
                    f'<hp:cellSz width="{width}" height="{row_height}"/><hp:cellMargin left="{mm(side_mm)}" right="{mm(side_mm)}" '
                    f'top="{mm(0.8)}" bottom="{mm(0.8)}"/></hp:tc>')
                col += cell.span
            body.append("<hp:tr>" + "".join(cells) + "</hp:tr>")
        total = sum(widths)
        tbl = (f'<hp:tbl id="{self.table_id}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
               f'dropcapstyle="None" pageBreak="TABLE" repeatHeader="{int(header_rows > 0)}" rowCnt="{len(rows)}" colCnt="{len(widths)}" '
               f'cellSpacing="0" borderFillIDRef="{B["cell"]}" noAdjust="0">'
               f'<hp:sz width="{total}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" protect="0"/>'
               f'<hp:pos treatAsChar="{int(whole)}" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
               f'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="{"CENTER" if center else "LEFT"}" vertOffset="0" horzOffset="0"/>'
               f'<hp:outMargin left="0" right="0" top="0" bottom="{_pt(pe.TABLE_AFTER)}"/>'
               f'<hp:inMargin left="{mm(side_mm)}" right="{mm(side_mm)}" top="{mm(0.8)}" bottom="{mm(0.8)}"/>{"".join(body)}</hp:tbl>')
        self.parts.append(f'<hp:p id="0" paraPrIDRef="{P[host]}" styleIDRef="0" pageBreak="{int(self.page_break)}" columnBreak="0" '
                          f'merged="0"><hp:run charPrIDRef="{C["body"]}">{tbl}<hp:t/></hp:run></hp:p>')
        self.page_break = False
        if not whole:
            # 떠 있는 긴 표 뒤 빈 문단 — 쪽 끝에 걸린 긴 표가 다음 쪽으로 밀리며 뒤 글 · 표가 앞 쪽에서 흘러 겹치거나 순서가 바뀌었다
            # (2.11.0 T1 · 11-14 완성본 09 · 02 · 08위 한글 2024 실측 — 빈 문단으로 풀림). 다시 읽기(`hwpx_paragraphs`)는 빈 문단을 뺀다.
            # ponytail: 본문 글자(11pt) 높이 한 줄 — 더 낮은 글자로 줄여도 겹침이 풀리는지는 한글로 다시 떠 볼 것
            self.parts.append(_TABLE_GAP)


def _labeled(text: str, char: str) -> list[Run]:
    """「라벨: 값」 — 라벨만 굵게(워드 판 `_labeled` 와 같은 규칙)."""
    found = pe._label_end(text)
    if not found:
        return [(text, char)]
    bold = "bold" if char == "body" else char
    return [(text[:found[0]], bold), (text[found[0]:], char)]


def _tag(sentence_type: Any, review: bool) -> list[Run]:
    mark = pe.TYPE_MARKS.get(sentence_type) if review else None
    return [(f"[{mark}] ", "tag")] if mark else []


def _source(text: str, sentence_type: Any, source: Any, review: bool) -> list[Run]:
    shown = pe._source_shown(text, sentence_type, source) if review else None
    return [(f" (근거: {shown})", "small")] if shown else []


def section_xml(blocks: list[pe.Block], *, review: bool) -> str:
    w = _Writer()
    for k, block in enumerate(blocks):
        kind = block[0]
        if kind == "field":
            if w.prev_kind == "field":
                continue
            end = k
            while end + 1 < len(blocks) and blocks[end + 1][0] == "field":
                end += 1
            _fields(w, [b[1:4] for b in blocks[k:end + 1]], review=review)
        elif kind == "cover":
            _cover(w, block[1], review=review)
        elif kind == "legend":
            lines = [([("검토용 — 제출하지 마세요", "warn")], "left"),
                     ([("회색 글자 — AI가 덧붙인 문장(근거 확인 후 고쳐 쓰기)", "ai")], "left"),
                     ([("[공고] [회사]", "tag"), (" — 공고 · 회사 근거가 있는 문장, 뒤에 (근거: …)", "memo")], "left"),
                     ([(HUMAN_INPUT, "memo"), (" — 담당자가 채웁니다", "memo")], "left")]
            w.table([[_Cell(lines, border="box")]], [TEXT_MM])
        elif kind == "toc":
            w.para([("목차", "h2")], "h2")
            for level, text in block[1]:
                w.para([(text, "bold" if level == 1 else "body")], "label" if level == 1 else "label_deep")
            w.page_break = True
        elif kind == "h1":
            w.para([(block[1], "h1")], "h1_top" if w.page_break or w.prev_kind is None else "h1")
        elif kind == "h2":
            runs: list[Run] = [(block[1], "h2")]
            count = pe._ai_count(block) if review else ""
            if count:
                runs.append(("  " + count, "small"))
            w.para(runs, "h2_tight" if w.prev_kind == "h1" else "h2")
        elif kind == "summary":
            lines = [([("핵심 요약(본문 첫 문장 자동 발췌)", "table_title")], "left")] + [([(f"· {line}", "memo")], "left") for line in block[1]]
            w.table([[_Cell(lines, border="box")]], [TEXT_MM])
        elif kind in pe.TEXT_KINDS:
            _text_block(w, block, review=review)
        elif kind == "photo":
            w.table([[_Cell([([(block[1], "cell")], "center")], height_mm=50)]], [TEXT_MM])
        elif kind in ("table", "memo_table"):
            _data_table(w, block[1])
        elif kind == "memo_h":
            w.page_break = True
            w.para([(block[1], "h1")], "h1_top")
        elif kind == "memo":
            _, text, depth = block
            found = next((i for i, ch in pe._outside(text) if ch in ":："), None) if pe._MEMO_BOLD.match(text) else None
            runs = [(text[:found + 1], "memo_bold"), (text[found + 1:], "memo")] if found is not None else [(text, "memo")]
            w.para(runs, "memo_deep" if depth else "memo")
        w.prev_kind = kind
    if w.parts and w.parts[-1] == _TABLE_GAP:
        # 문서 끝 긴 표 뒤 빈 문단은 뺀다 — 뒤 글이 없어 겹침을 막을 몫이 없고, 표가 쪽 바닥에서 끝나면 빈 마지막 쪽만 생긴다(2.11.0 A1 검토)
        w.parts.pop()
    return f'{_DECL}<hs:sec {_XMLNS}>{"".join(w.parts)}</hs:sec>'


def _text_block(w: _Writer, block: pe.Block, *, review: bool) -> None:
    kind, sentences, depth = block
    text, sentence_type, source = sentences[0]
    char = "ai" if review and sentence_type == SUGGESTION and kind != "sub" else "body"
    if kind == "sub":
        w.para([(text, "bold")], "sub_tight" if w.prev_kind == "h2" else "sub")
        return
    if kind == "item":
        glyph = pe._GLYPH.match(text)
        runs = [(glyph.group(1) + " ", char), *_tag(sentence_type, review), *_labeled(text[glyph.end():], char)]
        w.para(runs + _source(text, sentence_type, source, review), "item")
    elif kind == "dash":
        dash = pe._DASH.match(text)
        runs = [(dash.group(1) + " ", char), *_tag(sentence_type, review), (text[dash.end():], char)]
        w.para(runs + _source(text, sentence_type, source, review), "dash")
    elif kind == "label":
        runs = [*_tag(sentence_type, review), *_labeled(text, char)]
        w.para(runs + _source(text, sentence_type, source, review), "label_deep" if depth else "label")
    else:
        runs = [*_tag(sentence_type, review)]
        for i, (line, line_type, line_source) in enumerate(sentences):
            line_char = "ai" if review and line_type == SUGGESTION else "body"
            runs.append(((" " if i else "") + line, line_char))
            runs += _source(line, line_type, line_source, review)
        w.para(runs, "para_deep" if depth else "body")  # 표 뒤 간격은 표 바깥 여백(outMargin)이 맡는다


def _data_table(w: _Writer, table: dict[str, Any]) -> None:
    columns, rows = list(table.get("columns") or []), list(table.get("rows") or [])
    # 본문 6행 이하 표는 통째로 한 쪽에(워드 판 `build_docx.data_table` 과 같은 규칙)
    whole = len(rows) <= 6
    title = f"< {table['title']} >" if table.get("title") else None
    if title and whole:
        w.para([(title, "table_title")], "table_title")
    widths = list(table.get("widths_mm") or pe.column_mm(columns))
    # 월별 칸 표(24 · 36개월)는 칸 폭이 4~5mm 라 기본 칸 여백(좌우 1.8mm)이면 글자 자리가 없어 머리가 잘리고 표가 쪽 밖으로 넘쳤다(11-04 검토)
    # 25개월이 넘으면 머리는 숫자만 작은 글자로(「36월」이 3mm 칸에서 「36'」로 잘렸다 · 제목이 「월별」이라 뜻은 그대로)
    many = bool(table.get("grid")) and len(columns) > 25
    head = "grid_head" if many else "cell_bold"
    shown = [str(c)[:-1] if many and c != columns[0] and str(c).endswith("월") else str(c) for c in columns]
    # 한글은 3.6mm 칸의 가운데 정렬 글자를 약 1mm 오른쪽으로 밀어 두 자리 숫자가 칸 선에 걸렸다 — 숫자 머리는 왼쪽 정렬(11-04 한글 2024 실측)
    grid = [[_Cell([([(c, head)], "left" if many and k else "center")], border="head") for k, c in enumerate(shown)]]
    for row in rows:
        cells = []
        for c, column in enumerate(columns):
            value = str(row[c]) if c < len(row) else ""
            para = {"c": "center", "r": "right"}.get(pe.cell_align(column, value), "left")
            mark = "grid_mark_small" if many else "grid_mark"
            cells.append(_Cell([([(value, mark if value == "■" else "cell")], para)]))
        grid.append(cells)
    if title and not whole:
        # 떠 있는 긴 표에는 앞 문단 「다음과 함께」가 걸리지 않아 제목만 쪽 끝에 남았다(11-13 수정본 9쪽) — 테두리 없는 병합 첫 행으로 넣고
        # 칸 이름 줄과 함께 쪽마다 되풀이한다(2.10.0 T7 layout8 · 한글 2024 실측: 채움 문단 22~33 줄 중 「제목만」 자리가 사라짐)
        # ponytail: 남은 쪽이 제목 + 칸 이름 두 줄만 담는 자리(문단 한 줄 폭)에서는 두 줄이 쪽 끝에 남는다(옛 꼴도 같음 · 한글에 행 묶음
        # 설정이 없음) — 없애려면 머리 두 줄 + 첫 행을 글자처럼 취급한 작은 표로 떼어야 함
        grid.insert(0, [_Cell([([(title, "table_title")], "table_title")], border="none", span=len(columns))])
    w.table(grid, widths, header_rows=2 if title and not whole else 1, whole=whole, side_mm=0.3 if table.get("grid") else 1.8)


def _fields(w: _Writer, fields: list[tuple[str, str, str]], *, review: bool) -> None:
    rows: list[list[_Cell]] = []
    for row in pe.field_rows(fields):
        cells: list[_Cell] = []
        for label, value, origin in row:
            cells.append(_Cell([([(label, "cell_bold")], "center")], border="head"))
            photo = pe._photo_field(label, value)
            items = pe.split_items(value)
            # 「[회사자료]」는 칸 전체에 붙는 표식이라 워드 판처럼 마지막 조각 뒤에
            lines = [([(item, "cell")] + ([(" [회사자료]", "small")] if review and origin == "company" and j == len(items) - 1 else []),
                      "center" if photo else "left") for j, item in enumerate(items)]
            cells.append(_Cell(lines, span=3 if len(row) == 1 else 1, height_mm=50 if photo else 7))
        rows.append(cells)
    w.table(rows, [30, 53, 30, 53], whole=len(rows) <= pe.FIELDS_WHOLE_ROWS)  # 워드 판처럼 8행 이하는 통째로


def _cover(w: _Writer, info: dict[str, Any], *, review: bool) -> None:
    # 표지에는 쪽 번호를 숨긴다(워드 판: 첫 쪽 바닥글 없음)
    hide = ('<hp:ctrl><hp:pageHiding hideHeader="1" hideFooter="1" hideMasterPage="0" hideBorder="0" hideFill="0" '
            'hidePageNum="1"/></hp:ctrl>')
    w.para([(str(info.get("kind") or "사업계획서"), "cover_kind")], "cover_kind", ctrl=hide)
    w.para([(str(info.get("notice") or ""), "cover_notice")], "cover_band")
    link = pe.cover_link(info)
    # 링크 줄(10pt 두 줄)만큼 표를 올린다 — 워드 판 `250 − 줄 수 × 15pt` 와 같은 셈(2.9.1 검토: 검토용 붉은 상자가 2쪽으로 밀려 빈 쪽이 생겼다)
    w.para([], "cover_gap_link" if link else "cover_gap")
    rows = [[_Cell([([(label, "cover_label")], "right")], border="none"),
             _Cell([([(str(value) if value else HUMAN_INPUT, "cover_value")], "left")], border="none")]
            for label, value in pe.cover_rows(info)]
    if link:  # 「공고 원문」 — 하이퍼링크 필드(2.9.1 · 값 칸 글자는 주소 그대로)
        rows.append([_Cell([([(link[0], "cover_label")], "right")], border="none"),
                     _Cell([([(link[1], "cover_link")], "left")], border="none")])
    w.table(rows, [30, 90])
    if review:  # 붉은 상자 — 한글은 문단 테두리를 들여쓰기와 무관하게 쪽 너비로 그려서 한 칸 표로(워드 판 76mm 와 같은 폭)
        w.table([[_Cell([([("검토용 — 제출하지 마세요", "warn")], "center")], border="banner", height_mm=10)]], [TEXT_MM - 90],
                host="cover_banner")
    w.page_break = True


def _first_paragraph() -> str:
    """쪽 설정 · 단 · 쪽 번호 — 한글 2024 가 만든 공고서의 첫 문단 꼴 그대로.

    여백은 워드 판과 같은 본문 자리(위 22 · 아래 20mm)가 되게 한글 셈으로 옮긴다 — 한글은 본문 위 = 위 여백 + 머리말, 아래 = 아래 여백 + 꼬리말이다.
    워드 숫자(위 22 · 머리말 12)를 그대로 넣었더니 본문이 34mm 에서 시작해 같은 내용이 한 쪽 더 길었다(11-04 검토 · 한글이 워드를 옮기는 값과 같음)."""
    note = ('<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
            '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
            '<hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS" newNum="1"/>')
    borders = "".join(f'<hp:pageBorderFill type="{t}" borderFillIDRef="{B["none"]}" textBorder="PAPER" headerInside="0" footerInside="0" '
                      'fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>'
                      for t in ("BOTH", "EVEN", "ODD"))
    sec = ('<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" '
           'outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">'
           '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/><hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
           '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" '
           'hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/><hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
           f'<hp:pagePr landscape="WIDELY" width="59528" height="84188" gutterType="LEFT_ONLY"><hp:margin header="{mm(10)}" '
           f'footer="{mm(10)}" gutter="0" left="{mm(22)}" right="{mm(22)}" top="{mm(12)}" bottom="{mm(10)}"/></hp:pagePr>'
           f'<hp:footNotePr>{note}<hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr>'
           f'<hp:endNotePr>{note}<hp:placement place="END_OF_DOCUMENT" beneathText="0"/></hp:endNotePr>{borders}</hp:secPr>')
    ctrl = ('<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
            '<hp:ctrl><hp:pageNum pos="BOTTOM_CENTER" formatType="DIGIT" sideChar="-"/></hp:ctrl>')
    return (f'<hp:p id="0" paraPrIDRef="{P["left"]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{C["body"]}">{sec}{ctrl}</hp:run></hp:p>')


# ---------------------------------------------------------------------------
# 꾸러미
# ---------------------------------------------------------------------------


def _content_hpf(title: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (f'{_DECL}<opf:package {_XMLNS} version="" unique-identifier="" id=""><opf:metadata><opf:title>{escape(pe._clean(title))}</opf:title>'
            # 지은이는 비운다(한글 2024 원본처럼) — 「BidPilot AI」가 제출 파일의 문서 정보 · 한글로 만든 PDF 지은이에 남았다(11-04 검토)
            '<opf:language>ko</opf:language><opf:meta name="creator" content="text"/>'
            f'<opf:meta name="CreatedDate" content="text">{now}</opf:meta><opf:meta name="ModifiedDate" content="text">{now}</opf:meta>'
            '</opf:metadata><opf:manifest><opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
            '<opf:item id="settings" href="settings.xml" media-type="application/xml"/></opf:manifest>'
            '<opf:spine><opf:itemref idref="header" linear="no"/><opf:itemref idref="section0" linear="yes"/></opf:spine></opf:package>')


_VERSION = (f'{_DECL}<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" '
            'minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.5" application="" appVersion=""/>')
_CONTAINER = (f'{_DECL}<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">'
              '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
              '<ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/></ocf:rootfiles></ocf:container>')
_MANIFEST = f'{_DECL}<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
_SETTINGS = (f'{_DECL}<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
             'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"><ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>'
             '</ha:HWPApplicationSetting>')


def build_hwpx(draft: dict[str, Any], form: dict[str, Any], *, title: str, variant: pe.Variant = "submit",
               meta: dict[str, Any] | None = None) -> bytes:
    """HWPX 한 벌 — 제출용 · 검토용. mimetype 은 압축하지 않고 첫 멤버로 둔다(OCF)."""
    meta = {"notice": title, **(meta or {})}
    review = variant == "review"
    blocks = pe.document_blocks(draft, form, variant=variant, meta=meta)
    section = section_xml(blocks, review=review)
    section = section.replace(f"<hs:sec {_XMLNS}>", f"<hs:sec {_XMLNS}>{_first_paragraph()}", 1)
    preview = "\n".join(pe._block_text(b) for b in blocks if pe._block_text(b))[:2000]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), MIMETYPE, compress_type=zipfile.ZIP_STORED)
        for name, data in (("version.xml", _VERSION), ("Contents/header.xml", header_xml()), ("Contents/section0.xml", section),
                           ("Contents/content.hpf", _content_hpf(title)), ("META-INF/container.xml", _CONTAINER),
                           ("META-INF/manifest.xml", _MANIFEST), ("settings.xml", _SETTINGS), ("Preview/PrvText.txt", preview)):
            zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()
