"""HWPX 서식 템플릿 엔진 (PoC · Beta).

할 수 있는 것
- HWPX는 ZIP + XML(OWPML)이다. 기관 서식 HWPX를 **복사**한 뒤 본문(`Contents/section*.xml`)의
  `{{필드}}` 자리표시자를 값으로 바꾸고, 다시 ZIP으로 묶는다. 다른 멤버(헤더·스타일·미리보기)는 손대지 않는다.
- 자리표시자가 없는 서식을 위해 최소 구조의 HWPX(표 포함)를 직접 생성하는 내장 서식 5종을 둔다.
- 결과물은 ZIP 무결성·필수 멤버·XML 파싱을 검사하고, 텍스트를 다시 추출해 넣은 값이 실제로 들어갔는지 확인한다.
- 산출물마다 sha256 체크섬과 검증 보고서를 남긴다.

할 수 없는 것 (정직하게)
- **한컴오피스에서 실제로 열리는지는 이 환경에서 검증하지 못했다.** 내장 서식은 실제 HWPX 파일의
  구조를 본떠 최소한으로 만든 것이며, 스타일·글꼴·표 폭은 한컴에서 다시 잡아야 할 수 있다.
- HWP(5.0 바이너리)는 만들지 않는다. HWPX만 다룬다.
- 그래서 모든 산출물의 상태는 "beta"이며 화면에도 그렇게 표시한다.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from pydantic import BaseModel, Field

from app.core import storage
from app.core.paths import DATA_ROOT
from app.services import document_extractor

TEMPLATE_DIR = DATA_ROOT / "templates" / "hwpx"
REGISTRY_FILE = DATA_ROOT / "templates" / "registry.json"
EXPORT_DIR = DATA_ROOT / "public" / "exports"

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
REQUIRED_MEMBERS = ("mimetype", "Contents/content.hpf", "Contents/header.xml", "Contents/section0.xml", "META-INF/container.xml")
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
_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'


class TemplateNotFoundError(LookupError):
    """등록되지 않은 서식 id."""


class TemplateRenderError(RuntimeError):
    """렌더링·검증 실패."""


# --------------------------------------------------------------------------
# 서식 정의
# --------------------------------------------------------------------------


class TemplateField(BaseModel):
    key: str
    label: str
    # 값의 출처: company_profile | notice | requirements | manual (담당자 입력)
    source: str
    required: bool = False


class TemplateInfo(BaseModel):
    id: str
    title: str
    description: str
    kind: str  # builtin | agency
    status: str = "beta"
    fields: list[TemplateField]
    # agency 서식이면 파일명 (data/templates/hwpx 아래)
    file_name: str | None = None
    note: str


@dataclass
class _Table:
    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class _Doc:
    title: str
    paragraphs: list[str] = field(default_factory=list)
    tables: list[_Table] = field(default_factory=list)
    footer: list[str] = field(default_factory=list)


# 화면(한글 서식 칸)에 그대로 나가는 안내 — 「베타」 표시는 화면 머리 칩이 맡고, 파일 경로 · 영어는 쓰지 않는다 (DTL-23).
_COMMON_NOTE = "자동으로 채운 값은 회사 프로필 · 공고 정보 · 정리된 요구사항에서만 가져옵니다. 빈 칸은 담당자가 한컴오피스에서 직접 채워 주세요. 한컴오피스에서 제대로 열리는지는 아직 확인하지 못했습니다."

BUILTIN_TEMPLATES: dict[str, TemplateInfo] = {
    "bid_application": TemplateInfo(
        id="bid_application",
        title="입찰참가신청서",
        description="공고번호·공고명·발주기관과 신청인(상호·주소·전화)을 채운 신청서 서식",
        kind="builtin",
        fields=[
            TemplateField(key="notice_no", label="공고번호", source="notice", required=True),
            TemplateField(key="notice_title", label="공고명", source="notice", required=True),
            TemplateField(key="agency", label="발주기관", source="notice", required=True),
            TemplateField(key="company_name", label="상호", source="company_profile", required=True),
            TemplateField(key="company_address", label="주소", source="company_profile"),
            TemplateField(key="company_phone", label="전화", source="company_profile"),
            TemplateField(key="representative", label="대표자", source="manual"),
            TemplateField(key="corporate_number", label="법인등록번호", source="manual"),
        ],
        note=_COMMON_NOTE,
    ),
    "company_overview": TemplateInfo(
        id="company_overview",
        title="회사 일반현황",
        description="회사 프로필(상호·주소·사업영역·주요 고객·지역·인증)을 표로 정리",
        kind="builtin",
        fields=[
            TemplateField(key="company_name", label="상호", source="company_profile", required=True),
            TemplateField(key="company_address", label="주소", source="company_profile"),
            TemplateField(key="company_phone", label="전화", source="company_profile"),
            TemplateField(key="business_domains", label="사업영역", source="company_profile"),
            TemplateField(key="target_clients", label="주요 고객", source="company_profile"),
            TemplateField(key="preferred_regions", label="활동 지역", source="company_profile"),
            TemplateField(key="certifications", label="인증", source="company_profile"),
            TemplateField(key="founded_year", label="설립연도", source="manual"),
            TemplateField(key="employee_count", label="임직원 수", source="manual"),
        ],
        note=_COMMON_NOTE,
    ),
    "performance_table": TemplateInfo(
        id="performance_table",
        title="수행실적표",
        description="실적 원장(외부 성공연혁=가능 행)의 교육·컨설팅·사업 수행 실적으로 행을 채운다. 원장이 없으면 빈 표.",
        kind="builtin",
        fields=[
            TemplateField(key="notice_title", label="공고명", source="notice"),
            TemplateField(key="company_name", label="상호", source="company_profile", required=True),
            TemplateField(key="performance_rows", label="실적 행", source="ledger"),
        ],
        note=_COMMON_NOTE + " 실적 행은 회사 실적 원장에서 채택한 행입니다 — 제출 전에 계약서 · 계산서 · 완료확인서와 대조해 주세요.",
    ),
    "staffing_table": TemplateInfo(
        id="staffing_table",
        title="투입인력표",
        description="인력 행은 채우지 않는다 (개인정보). 표 틀과 공고 정보만 채운다.",
        kind="builtin",
        fields=[
            TemplateField(key="notice_title", label="공고명", source="notice"),
            TemplateField(key="company_name", label="상호", source="company_profile", required=True),
        ],
        note=_COMMON_NOTE + " 인력 행은 개인정보라 채우지 않습니다.",
    ),
    "requirement_matrix": TemplateInfo(
        id="requirement_matrix",
        title="요구사항 대응표",
        description="파싱된 항목(코드·유형·내용·페이지)을 표로 옮긴다. 대응 내용 칸은 비워 둔다.",
        kind="builtin",
        fields=[
            TemplateField(key="notice_title", label="공고명", source="notice"),
            TemplateField(key="company_name", label="상호", source="company_profile", required=True),
            TemplateField(key="requirements", label="항목 목록", source="requirements", required=True),
        ],
        note=_COMMON_NOTE,
    ),
}


def list_templates() -> list[TemplateInfo]:
    templates = list(BUILTIN_TEMPLATES.values())
    registry = storage.read_json(REGISTRY_FILE, default=None)
    if isinstance(registry, dict):
        for item in registry.get("templates", []):
            try:
                info = TemplateInfo.model_validate({**item, "kind": "agency", "status": "beta"})
            except ValueError:
                continue
            if info.file_name and (TEMPLATE_DIR / info.file_name).exists():
                templates.append(info)
    return templates


def get_template(template_id: str) -> TemplateInfo:
    for template in list_templates():
        if template.id == template_id:
            return template
    raise TemplateNotFoundError(template_id)


# --------------------------------------------------------------------------
# 최소 HWPX 생성 (내장 서식)
# --------------------------------------------------------------------------


def _para(text: str, *, char_pr: int = 0, para_pr: int = 0) -> str:
    runs = f'<hp:run charPrIDRef="{char_pr}"><hp:t>{escape(text)}</hp:t></hp:run>' if text else f'<hp:run charPrIDRef="{char_pr}"/>'
    return f'<hp:p id="0" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">{runs}</hp:p>'


def _cell(text: str, *, header: bool) -> str:
    return (
        f'<hp:tc name="" header="{1 if header else 0}" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="3">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f"{_para(text, char_pr=1 if header else 0)}</hp:subList></hp:tc>"
    )


def _table(table: _Table) -> str:
    rows = [table.headers] + (table.rows or [[""] * len(table.headers)])
    body = "".join("<hp:tr>" + "".join(_cell(c, header=(i == 0)) for c in row) + "</hp:tr>" for i, row in enumerate(rows))
    col = len(table.headers)
    return (
        f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        f'<hp:tbl id="0" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="1" rowCnt="{len(rows)}" colCnt="{col}" cellSpacing="0" borderFillIDRef="3" noAdjust="0">'
        f'<hp:sz width="48000" widthRelTo="ABSOLUTE" height="{1200 * len(rows)}" heightRelTo="ABSOLUTE" protect="0"/>'
        f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
        f'<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="141" right="141" top="141" bottom="141"/>'
        f"{body}</hp:tbl></hp:run></hp:p>"
    )


def _section_xml(doc: _Doc) -> str:
    parts = [
        f"{_XML_DECL}<hs:sec {_XMLNS}>",
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">'
        '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/><hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
        '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
        '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
        '<hp:pagePr landscape="WIDELY" width="59528" height="84188" gutterType="LEFT_ONLY"><hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/></hp:pagePr>'
        '</hp:secPr><hp:t>' + escape(doc.title) + "</hp:t></hp:run></hp:p>",
    ]
    for text in doc.paragraphs:
        parts.append(_para(text))
    for table in doc.tables:
        parts.append(_table(table))
        parts.append(_para(""))
    for text in doc.footer:
        parts.append(_para(text))
    parts.append("</hs:sec>")
    return "".join(parts)


def _header_xml() -> str:
    return (
        f'{_XML_DECL}<hh:head {_XMLNS} version="1.4" secCnt="1">'
        '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
        "<hh:refList>"
        '<hh:fontfaces itemCnt="7">'
        + "".join(
            f'<hh:fontface lang="{lang}" fontCnt="1"><hh:font id="0" face="함초롬돋움" type="TTF" isEmbedded="0"/></hh:fontface>'
            for lang in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
        )
        + "</hh:fontfaces>"
        '<hh:borderFills itemCnt="3">'
        '<hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/><hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/><hh:topBorder type="NONE" width="0.1 mm" color="#000000"/><hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/><hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/></hh:borderFill>'
        '<hh:borderFill id="2" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/><hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/><hh:topBorder type="NONE" width="0.1 mm" color="#000000"/><hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/><hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/></hh:borderFill>'
        '<hh:borderFill id="3" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/><hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/><hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/><hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/><hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/></hh:borderFill>'
        "</hh:borderFills>"
        '<hh:charProperties itemCnt="2">'
        '<hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/><hh:shadow type="NONE" color="#B2B2B2" offsetX="10" offsetY="10"/></hh:charPr>'
        '<hh:charPr id="1" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:bold/><hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/><hh:shadow type="NONE" color="#B2B2B2" offsetX="10" offsetY="10"/></hh:charPr>'
        "</hh:charProperties>"
        '<hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties>'
        '<hh:numberings itemCnt="1"><hh:numbering id="1" start="0"/></hh:numberings>'
        '<hh:paraProperties itemCnt="1"><hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"><hh:align horizontal="JUSTIFY" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/><hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="BREAK_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/><hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin><hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/><hh:border borderFillIDRef="2" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/></hh:paraPr></hh:paraProperties>'
        '<hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>'
        "</hh:refList>"
        '<hh:compatibleDocument targetProgram="HWP201X"><hh:layoutCompatibility/></hh:compatibleDocument>'
        '<hh:docOption><hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/></hh:docOption>'
        "</hh:head>"
    )


def _content_hpf(title: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f'{_XML_DECL}<opf:package {_XMLNS} version="" unique-identifier="" id="">'
        f"<opf:metadata><opf:title>{escape(title)}</opf:title><opf:language>ko</opf:language>"
        '<opf:meta name="creator" content="text">BidPilot AI (beta)</opf:meta>'
        f'<opf:meta name="CreatedDate" content="text">{now}</opf:meta><opf:meta name="ModifiedDate" content="text">{now}</opf:meta></opf:metadata>'
        '<opf:manifest><opf:item id="header" href="Contents/header.xml" media-type="application/xml"/><opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/><opf:item id="settings" href="settings.xml" media-type="application/xml"/></opf:manifest>'
        '<opf:spine><opf:itemref idref="header" linear="no"/><opf:itemref idref="section0" linear="no"/></opf:spine></opf:package>'
    )


_VERSION_XML = f'{_XML_DECL}<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="0" buildNumber="1" os="1" xmlVersion="1.4" application="BidPilot AI" appVersion="beta"/>'
_CONTAINER_XML = f'{_XML_DECL}<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf"><ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/><ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/></ocf:rootfiles></ocf:container>'
_MANIFEST_XML = f'{_XML_DECL}<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
_SETTINGS_XML = f'{_XML_DECL}<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"><ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/></ha:HWPApplicationSetting>'


def build_minimal_hwpx(doc: _Doc) -> bytes:
    """실제 HWPX 파일 구조를 본뜬 최소 문서. mimetype은 압축하지 않고 첫 멤버로 둔다."""
    preview = "\n".join([doc.title, *doc.paragraphs, *(" | ".join(t.headers) for t in doc.tables), *doc.footer])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("version.xml", _VERSION_XML, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("Contents/content.hpf", _content_hpf(doc.title), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("Contents/header.xml", _header_xml(), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("Contents/section0.xml", _section_xml(doc), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("META-INF/container.xml", _CONTAINER_XML, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("META-INF/manifest.xml", _MANIFEST_XML, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("settings.xml", _SETTINGS_XML, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("Preview/PrvText.txt", preview, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# 기관 서식 자리표시자 치환
# --------------------------------------------------------------------------


def replace_placeholders(template_bytes: bytes, values: dict[str, str]) -> tuple[bytes, list[str]]:
    """section*.xml 안의 {{key}}를 값으로 바꾼다. 못 채운 자리표시자 목록을 함께 돌려준다."""
    unresolved: list[str] = []
    with zipfile.ZipFile(io.BytesIO(template_bytes)) as src:
        if src.testzip() is not None:
            raise TemplateRenderError("서식 ZIP이 손상되어 있습니다")
        members = src.infolist()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as dst:
            for info in members:
                data = src.read(info.filename)
                if document_extractor._SECTION_RE.match(info.filename):
                    text = data.decode("utf-8")

                    def _sub(match: re.Match[str]) -> str:
                        key = match.group(1)
                        if key in values:
                            return escape(values[key])
                        unresolved.append(key)
                        return match.group(0)

                    text = PLACEHOLDER_RE.sub(_sub, text)
                    data = text.encode("utf-8")
                compress = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
                dst.writestr(info.filename, data, compress_type=compress)
    return out.getvalue(), sorted(set(unresolved))


# --------------------------------------------------------------------------
# 검증
# --------------------------------------------------------------------------


class ValidationReport(BaseModel):
    zip_ok: bool
    required_members_ok: bool
    missing_members: list[str]
    xml_ok: bool
    xml_errors: list[str]
    mimetype_ok: bool
    section_count: int


class VerificationReport(BaseModel):
    """텍스트를 다시 추출해 넣은 값이 실제로 들어갔는지."""

    extracted_chars: int
    fields_checked: int
    fields_found: int
    missing_fields: list[str]
    unresolved_placeholders: list[str]


class RenderResult(BaseModel):
    template_id: str
    template_title: str
    procurement_id: str
    status: str = "beta"
    verified: bool
    file_name: str
    download_path: str
    size_bytes: int
    sha256: str
    rendered_at: datetime
    values: dict[str, str]
    validation: ValidationReport
    verification: VerificationReport
    note: str


def validate_hwpx(payload: bytes) -> ValidationReport:
    errors: list[str] = []
    missing: list[str] = []
    sections = 0
    mimetype_ok = False
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            zip_ok = zf.testzip() is None
            names = set(zf.namelist())
            missing = [m for m in REQUIRED_MEMBERS if m not in names]
            if "mimetype" in names:
                mimetype_ok = zf.read("mimetype").decode("utf-8", "replace").strip() == MIMETYPE
            for name in names:
                if name.endswith(".xml") or name.endswith(".hpf"):
                    try:
                        ET.fromstring(zf.read(name))
                    except ET.ParseError as exc:
                        errors.append(f"{name}: {exc}")
                if document_extractor._SECTION_RE.match(name):
                    sections += 1
    except zipfile.BadZipFile as exc:
        return ValidationReport(zip_ok=False, required_members_ok=False, missing_members=list(REQUIRED_MEMBERS), xml_ok=False, xml_errors=[str(exc)], mimetype_ok=False, section_count=0)
    return ValidationReport(
        zip_ok=zip_ok,
        required_members_ok=not missing,
        missing_members=missing,
        xml_ok=not errors,
        xml_errors=errors,
        mimetype_ok=mimetype_ok,
        section_count=sections,
    )


def verify_by_reextract(path: Path, values: dict[str, str], unresolved: list[str]) -> VerificationReport:
    pages = document_extractor.extract_hwpx(path)
    text = re.sub(r"\s+", "", "\n".join(p.text for p in pages))
    checked = {k: v for k, v in values.items() if v and v.strip()}
    missing = [k for k, v in checked.items() if re.sub(r"\s+", "", v)[:60] not in text]
    return VerificationReport(
        extracted_chars=len(text),
        fields_checked=len(checked),
        fields_found=len(checked) - len(missing),
        missing_fields=missing,
        unresolved_placeholders=unresolved,
    )


# --------------------------------------------------------------------------
# 값 모으기 + 렌더링
# --------------------------------------------------------------------------


def _join(items: list[str]) -> str:
    return ", ".join(i for i in items if i)


def collect_values(template: TemplateInfo, *, profile: Any, notice: Any | None, parse_result: Any | None, manual: dict[str, str] | None) -> dict[str, str]:
    """서식 필드 값. 출처가 없는 값은 빈 문자열로 둔다 (지어내지 않는다)."""
    manual = manual or {}
    values: dict[str, str] = {}
    for f in template.fields:
        value = ""
        if f.source == "company_profile" and profile is not None:
            mapping = {
                "company_name": profile.name,
                "company_address": profile.address or "",
                "company_phone": profile.phone or "",
                "business_domains": _join(profile.business_domains),
                "target_clients": _join(profile.target_clients),
                "preferred_regions": _join(profile.preferred_regions),
                "certifications": _join(profile.certifications),
            }
            value = str(mapping.get(f.key, "") or "")
        elif f.source == "notice" and notice is not None:
            mapping = {"notice_no": notice.notice_no, "notice_title": notice.title, "agency": notice.agency}
            value = str(mapping.get(f.key, "") or "")
        elif f.source in ("requirements", "ledger"):
            value = ""  # 표로 따로 넣는다
        if f.key in manual and manual[f.key].strip():
            value = manual[f.key].strip()
        values[f.key] = value
    return values


def _ledger_amount(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.1f}"


def performance_rows(ledger_rows: list[dict[str, Any]] | None) -> list[list[str]]:
    """원장 행 → 수행실적표 행. 최신 연도 우선. 원장 셀 값만 옮긴다."""
    rows: list[list[str]] = []
    ordered = sorted(
        ledger_rows or [],
        key=lambda r: (-(max((int(n) for n in re.findall(r"20\d{2}", f"{r.get('year','')} {r.get('period','')}")), default=0)), -(r.get("amount_thousand_krw") or 0)),
    )
    for index, row in enumerate(ordered, start=1):
        rows.append(
            [
                str(index),
                str(row.get("title") or ""),
                str(row.get("agency") or ""),
                str(row.get("period") or row.get("year") or ""),
                (f"{_ledger_amount(row.get('amount_thousand_krw'))}천원" if row.get("amount_thousand_krw") is not None else ""),
                str(row.get("evidence_note") or ""),
            ]
        )
    return rows


def _doc_for(template: TemplateInfo, values: dict[str, str], parse_result: Any | None, ledger_rows: list[dict[str, Any]] | None = None) -> _Doc:
    title = template.title
    if template.id == "bid_application":
        return _Doc(
            title=f"입찰참가신청서",
            paragraphs=[],
            tables=[
                _Table(headers=["공고번호", values["notice_no"]]),
                _Table(headers=["공고명", values["notice_title"]]),
                _Table(headers=["발주기관", values["agency"]]),
                _Table(headers=["상호", values["company_name"]]),
                _Table(headers=["주소", values["company_address"]]),
                _Table(headers=["전화", values["company_phone"]]),
                _Table(headers=["대표자", values["representative"]]),
                _Table(headers=["법인등록번호", values["corporate_number"]]),
            ],
            footer=["위와 같이 입찰에 참가하고자 신청합니다.", "신청인: ________________ (인)  ·  담당자 확인 후 제출"],
        )
    if template.id == "company_overview":
        rows = [
            ["상호", values["company_name"]],
            ["주소", values["company_address"]],
            ["전화", values["company_phone"]],
            ["사업영역", values["business_domains"]],
            ["주요 고객", values["target_clients"]],
            ["활동 지역", values["preferred_regions"]],
            ["인증", values["certifications"]],
            ["설립연도", values["founded_year"]],
            ["임직원 수", values["employee_count"]],
        ]
        return _Doc(title="회사 일반현황", tables=[_Table(headers=["항목", "내용"], rows=rows)])
    if template.id == "performance_table":
        rows = performance_rows(ledger_rows)
        return _Doc(
            title=f"수행실적표 — {values['company_name']}",
            paragraphs=[f"공고명: {values['notice_title']}"] if values.get("notice_title") else [],
            tables=[_Table(headers=["연번", "사업명", "발주기관", "계약기간", "계약금액(천원)", "증빙 기준"], rows=rows or [["1", "", "", "", "", "담당자 작성"]])],
            footer=[
                f"실적 {len(rows)}건 — 실적 원장 「외부 성공연혁 = 가능」 행 중 교육·컨설팅·사업 수행 실적만. 제출 전 계약서·계산서·완료확인서와 대조한다."
                if rows
                else "실적 원장이 없어 행을 채우지 않았다. 담당자가 계약서 기준으로 직접 적는다."
            ],
        )
    if template.id == "staffing_table":
        return _Doc(
            title=f"투입인력표 — {values['company_name']}",
            paragraphs=[f"공고명: {values['notice_title']}"] if values.get("notice_title") else [],
            tables=[_Table(headers=["연번", "역할", "성명", "경력", "자격", "투입률"], rows=[["1", "", "", "", "", ""]])],
            footer=["인력 행은 개인정보라 시스템이 채우지 않는다."],
        )
    if template.id == "requirement_matrix":
        rows: list[list[str]] = []
        if parse_result is not None:
            for req in parse_result.requirements:
                code = req.display_code or req.requirement_id
                rows.append([code, str(req.item_type), req.content[:200], f"p.{req.page}" if req.page else "-", ""])
        return _Doc(
            title=f"요구사항 대응표 — {values['notice_title'] or values['company_name']}",
            tables=[_Table(headers=["코드", "유형", "요구사항", "페이지", "대응 내용(담당자 작성)"], rows=rows)],
            footer=[
                f"제안사: {values['company_name']}",
                f"항목 {len(rows)}건 · 페이지는 HWP/HWPX의 경우 문단 묶음 근사값이다." if rows else "파싱된 항목이 없다.",
            ],
        )
    return _Doc(title=title)


def render(
    template_id: str,
    procurement_id: str,
    *,
    profile: Any,
    notice: Any | None,
    parse_result: Any | None,
    manual: dict[str, str] | None = None,
    ledger_rows: list[dict[str, Any]] | None = None,
    context: Any | None = None,
) -> RenderResult:
    template = get_template(template_id)
    values = collect_values(template, profile=profile, notice=notice, parse_result=parse_result, manual=manual)
    missing_required = [f.label for f in template.fields if f.required and f.source != "requirements" and not values.get(f.key)]
    if missing_required:
        raise TemplateRenderError(f"필수 값이 비어 있습니다: {', '.join(missing_required)}")
    if template.id == "requirement_matrix" and (parse_result is None or not parse_result.requirements):
        raise TemplateRenderError("정리된 요구사항이 없어 대응표를 만들 수 없습니다. 공고 분석을 먼저 해 주세요.")

    unresolved: list[str] = []
    if template.kind == "agency" and template.file_name:
        source = (TEMPLATE_DIR / template.file_name).read_bytes()
        payload, unresolved = replace_placeholders(source, values)
    else:
        payload = build_minimal_hwpx(_doc_for(template, values, parse_result, ledger_rows))

    validation = validate_hwpx(payload)
    if not (validation.zip_ok and validation.required_members_ok and validation.xml_ok):
        raise TemplateRenderError(f"생성한 HWPX가 검증에 실패했습니다: {validation.model_dump()}")

    safe_pid = storage.safe_id(procurement_id, what="공고 id")
    out_dir = export_dir(safe_pid, context)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{template.id}.hwpx"
    target = out_dir / file_name
    tmp = target.with_suffix(".hwpx.tmp")
    tmp.write_bytes(payload)
    tmp.replace(target)

    verification = verify_by_reextract(target, {k: v for k, v in values.items() if k not in ("requirements", "performance_rows")}, unresolved)
    verified = verification.fields_found == verification.fields_checked and not unresolved
    result = RenderResult(
        template_id=template.id,
        template_title=template.title,
        procurement_id=procurement_id,
        verified=verified,
        file_name=file_name,
        download_path=f"/api/exports/{safe_pid}/{file_name}" + (f"?organization_id={context.organization_id}&evidence_scope={context.evidence_scope}" if context is not None else ""),
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        rendered_at=datetime.now(timezone.utc),
        values=values,
        validation=validation,
        verification=verification,
        note=template.note + (" 자리표시자 미치환: " + ", ".join(unresolved) if unresolved else ""),
    )
    storage.write_json_atomic(out_dir / f"{template.id}.report.json", storage.stamp(result.model_dump(mode="json")))
    return result


def export_dir(safe_pid: str, context: Any | None = None) -> Path:
    """산출물 폴더. internal 컨텍스트면 조직 분석 폴더 아래(exports/), 아니면 공개 위치."""
    from app.services import analysis_store

    if analysis_store.is_private(context):
        return analysis_store.private_dir(context, safe_pid) / "exports"
    return EXPORT_DIR / safe_pid


def export_path(procurement_id: str, file_name: str, context: Any | None = None) -> Path:
    safe_pid = storage.safe_id(procurement_id, what="공고 id")
    if not re.match(r"^[A-Za-z0-9_\-]{1,60}\.hwpx$", file_name):
        raise TemplateNotFoundError(file_name)
    return export_dir(safe_pid, context) / file_name


def load_report(procurement_id: str, template_id: str, context: Any | None = None) -> RenderResult | None:
    safe_pid = storage.safe_id(procurement_id, what="공고 id")
    payload = storage.read_json(export_dir(safe_pid, context) / f"{template_id}.report.json", default=None)
    return RenderResult.model_validate(payload) if isinstance(payload, dict) else None
