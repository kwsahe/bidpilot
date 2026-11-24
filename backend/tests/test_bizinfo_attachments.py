"""기업마당 첨부파일 — 「@」로 이어 붙은 칸을 나눠 짝짓는다 (ISSUE-111 · prompt_01 §4-C).

## 무엇이 틀렸나

담당자가 짚었다: 「신청 서식 링크가 내려받기·출력이 안 돼. 공고문은 됨.」

기업마당 API 는 첨부가 여럿이면 **이름도 주소도 한 칸에 「@」로 이어** 준다.
126482(공공데이터 오픈이노베이션)의 실제 캐시 값이 그렇다 — 파일 셋인데
`fileNm` 은 「a.hwpx@b.pdf@c.pdf」, `flpthNm` 은 「url1@url2@url3」 한 덩어리다.
`_attachments` 가 그 문자열을 통째로 이름 하나·주소 하나로 만들어서 링크가
세 주소를 이어 붙인 쓰레기가 됐다. 공고문(`printFileNm`)은 파일이 하나뿐이라
우연히 멀쩡했다 — 그래서 「공고문은 된다」고 보였던 것이다.

거기에 하나 더: 목록이 주는 주소는 `getImageFile.do` 인데 **그건 뷰어 HTML** 이다
(0924.md §2 실측, 26/26 확인). 원본은 같은 `atchFileId`·`fileSn` 으로
`fileDown.do` 를 부를 때 온다.

## 여기서 지키는 약속

1. 이름과 주소를 각각 「@」로 나눠 **차례대로** 짝짓는다.
2. 화면 링크는 **내려받기 주소**, 원래 뷰어 주소는 `view_url` 로 남긴다.
3. 개수가 어긋나면 **주소 수만큼** 만들고 모자란 이름은 「파일 n」.
4. 값은 **캐시 필드값으로만** 검증한다 — 파일 서버를 부르지 않는다(실호출 0회).
"""

from __future__ import annotations

from app.services.bizinfo_service import _attachments

# 126482 캐시 실측값 (data/private/cache/bizinfo/bizinfo_cache.json).
# 주소를 부르지 않는다 — 문자열만 쓴다.
_BASE = "https://www.bizinfo.go.kr/cmm/fms/getImageFile.do?atchFileId=FILE_000000000773432"
ITEM_126482 = {
    "pblancId": "PBLN_000000000126482",
    "fileNm": (
        "「민관협력_오픈이노베이션_지원」공공데이터_활용_지원_공공기관_제안형(Top-Down)_창업기업_모집공고.hwpx"
        "@[별첨_2]_사업_신청_매뉴얼.pdf"
        "@[별첨_1]_공공기관_과제소개서.pdf"
    ),
    "flpthNm": f"{_BASE}&fileSn=1@{_BASE}&fileSn=2@{_BASE}&fileSn=3",
    "printFileNm": "「민관협력_오픈이노베이션_지원」공공데이터_활용_지원_공공기관_제안형(Top-Down)_창업기업_모집공고.pdf",
    "printFlpthNm": "https://www.bizinfo.go.kr/cmm/fms/getImageFile.do?atchFileId=FILE_000000000773431&fileSn=1",
}


def test_126482_세_파일이_세_건으로_갈린다() -> None:
    """한 덩어리였던 신청 서식이 세 줄이 된다. 공고문은 그대로 한 줄."""
    result = _attachments(ITEM_126482)

    # 30차 §3-A — 신청 서식 칸(fileNm)은 이름으로 종류를 단다(공고문 hwpx · 매뉴얼 · 과제소개서). 칸 안 순번으로 가른다.
    forms = [a for a in result if a.index is not None]
    notices = [a for a in result if a.index is None]

    assert len(forms) == 3, "신청 서식 칸 세 파일"
    assert len(notices) == 1, "공고문은 원래 한 파일"

    assert [a.name for a in forms] == [
        "「민관협력_오픈이노베이션_지원」공공데이터_활용_지원_공공기관_제안형(Top-Down)_창업기업_모집공고.hwpx",
        "[별첨_2]_사업_신청_매뉴얼.pdf",
        "[별첨_1]_공공기관_과제소개서.pdf",
    ]
    # 주소가 셋으로 갈리고 fileSn 이 하나씩 붙는다.
    assert [a.url for a in forms] == [
        f"https://www.bizinfo.go.kr/cmm/fms/fileDown.do?atchFileId=FILE_000000000773432&fileSn={n}"
        for n in (1, 2, 3)
    ]


def test_화면_링크는_내려받기_주소다() -> None:
    """뷰어(`getImageFile.do`)는 보조 링크로만 남는다."""
    for attachment in _attachments(ITEM_126482):
        assert "fileDown.do" in attachment.url
        assert "getImageFile.do" not in attachment.url
        assert attachment.view_url is not None
        assert "getImageFile.do" in attachment.view_url
        # 같은 파일을 가리켜야 한다 — 경로만 다르다.
        assert attachment.view_url.replace("getImageFile.do", "fileDown.do") == attachment.url


def test_확장자_배지() -> None:
    forms = [a for a in _attachments(ITEM_126482) if a.index is not None]  # 신청 서식 칸(30차 — 종류는 이름으로)
    assert [a.ext for a in forms] == ["hwpx", "pdf", "pdf"]
    notice = next(a for a in _attachments(ITEM_126482) if a.index is None)
    assert notice.ext == "pdf"


def test_단일_파일은_그대로_한_건() -> None:
    """A1 처럼 「@」가 없는 공고는 예전과 같은 결과여야 한다(건수 1)."""
    item = {
        "fileNm": "신청서.hwp",
        "flpthNm": "https://www.bizinfo.go.kr/cmm/fms/getImageFile.do?atchFileId=FILE_A&fileSn=1",
    }
    result = _attachments(item)
    assert len(result) == 1
    assert result[0].name == "신청서.hwp"
    assert result[0].url == "https://www.bizinfo.go.kr/cmm/fms/fileDown.do?atchFileId=FILE_A&fileSn=1"
    assert result[0].ext == "hwp"


def test_이름이_모자라면_파일_n() -> None:
    """이름 2 · 주소 3 → 3건, 세 번째는 「파일 3」 (프롬프트 §4-C-4)."""
    item = {
        "fileNm": "가.hwp@나.pdf",
        "flpthNm": "https://x/getImageFile.do?a=1@https://x/getImageFile.do?a=2@https://x/getImageFile.do?a=3",
    }
    result = _attachments(item)
    assert len(result) == 3
    assert [a.name for a in result] == ["가.hwp", "나.pdf", "파일 3"]
    # 이름이 없으면 확장자도 없다 — 지어내지 않는다.
    assert result[2].ext is None


def test_주소가_없으면_한_건도_만들지_않는다() -> None:
    """이름만 있고 주소가 없으면 눌러도 갈 곳이 없다."""
    assert _attachments({"fileNm": "가.hwp@나.pdf"}) == []
    assert _attachments({}) == []


def test_이름이_더_많아도_주소_수만큼() -> None:
    """이름 3 · 주소 1 → 1건. 주소 없는 줄은 만들지 않는다."""
    item = {"fileNm": "가.hwp@나.pdf@다.pdf", "flpthNm": "https://x/getImageFile.do?a=1"}
    result = _attachments(item)
    assert len(result) == 1
    assert result[0].name == "가.hwp"
