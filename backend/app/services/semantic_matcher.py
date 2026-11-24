"""공고와 회사 프로필의 **의미** 유사도 (CLAUDE.md §4-C · 0917.md §4-3).

## 무엇을 고치는가

지금까지 「우리 회사 적합도」는 키워드 포함 여부였다. 화면도 그렇게 적었다 —
「의미매칭 미실행」. 그래서 이런 일이 생긴다.

    「AI GPU 서버 구축」          — 「AI」가 들어 있어 후보로 올라온다
    「생성형 AI 활용 실무교육 운영」 — 역시 후보다. 둘의 점수가 비슷하다

키워드는 **글자가 같은지**만 본다. 샘플에듀가 하는 일(교육·컨설팅)과 공고가 요구하는 일이
얼마나 가까운지는 글자로 판단할 수 없다. 임베딩 코사인은 그 거리를 잰다.

## 어떻게

회사 프로필 문장(사업영역·주요 고객·활동 지역·인증)을 **문구 단위로** 임베딩해 두고,
공고 텍스트와의 코사인 중 **가장 가까운 문구**를 찾는다. 그 문구가 그대로 사유가 된다 —
「어느 사업영역과 가까운가」를 사람이 읽을 수 있어야 점수를 믿을 수 있다.

평균이 아니라 최댓값을 쓰는 이유: 회사가 사업영역을 여섯 개 적었을 때, 공고가 그중 하나와
아주 가까우면 그것으로 충분하다. 평균을 내면 「무엇이든 조금씩 하는 회사」가 불리해진다.

## 키가 없으면

`method="KEYWORD"` 로 **기존 규칙 결과를 그대로** 돌려주고 `fit_score=None` 이다.
없는 값을 0 으로 채우지 않는다 (CLAUDE.md §12 — 미확인은 0점이 아니다).

## 돈

임베딩은 내용 해시로 디스크에 캐시한다(`data/private/cache/embeddings/`). 같은 공고·같은
프로필 문장은 두 번 부르지 않는다. 목록 한 번에 공고 100건이 들어오므로 캐시가 없으면
호출이 100번 난다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from app.core.paths import DATA_ROOT
from app.services import llm_client

logger = logging.getLogger(__name__)

CACHE_DIR: Final[Path] = DATA_ROOT / "private" / "cache" / "embeddings"

#: 「높음/보통/낮음」 경계. 코사인 원값이 아니라 아래 `_normalize` 를 지난 값 기준이다.
HIGH_THRESHOLD: Final[float] = 0.62
MID_THRESHOLD: Final[float] = 0.42

#: 한국어 임베딩의 코사인은 무관한 문장 사이에서도 0.6 안팎이 나온다 — **가정이다.**
#: 이 저장소에서 잰 값이 아니다(크레딧이 없어 실제 임베딩을 한 번도 돌리지 못했다).
#: 그 가정이 맞다면 원값을 그대로 쓸 때 모든 공고가 「높음」이 되므로, 실질 구간으로 본
#: 0.55~0.90 을 0~1 로 편다. 크레딧이 생기면 **가장 먼저 이 두 값을 실측으로 바꿔야 한다.**
_COSINE_FLOOR: Final[float] = 0.55
_COSINE_CEIL: Final[float] = 0.90

#: 공고 텍스트가 이보다 짧으면 판정하지 않는다 — 제목만으로는 의미를 재기 어렵다.
MIN_TEXT_CHARS: Final[int] = 10

#: 합성 벡터를 읽어도 되는가. **운영에서는 절대 켜지 않는다.**
#: 시험용 합성 벡터(`store_cached(..., synthetic=True)`)가 실제 캐시에 섞이면 운영이 그것을
#: 진짜 임베딩으로 쓰고 화면에 「AI 의미 매칭」이라 적는다 — 잰 적 없는 값을 쟀다고 말하게 된다.
#: 순서 시험(`tests/test_semantic_matching_order.py`)만 tmp 캐시에서 이 값을 켠다.
ALLOW_SYNTHETIC_VECTORS: bool = False

MatchMethod = Literal["EMBEDDING", "KEYWORD"]
FitLabel = Literal["높음", "보통", "낮음"]

#: 스위치가 꺼져 있을 때의 사유. 「키가 없다」와 다른 사실이라 문장을 따로 둔다.
SEMANTIC_OFF_REASON = (
    "AI 의미 매칭은 꺼 두어 낱말 기준으로만 판정했습니다 "
    "(점수가 바뀌지 않게 고정 — 켜는 것은 서버 설정)."  # 설정 이름은 화면에 적지 않는다(27차 §3-H)
)


def semantic_fit_enabled() -> bool:
    """의미 유사도를 **점수에 쓸 것인가** (ISSUE-129 · prompt_05 §4-A-1).

    없으면 **꺼짐**이다. `llm_client.embedding_live_enabled()` 와 다른 문이다 —
    저쪽은 「바깥을 부르는가」이고 이쪽은 「점수에 쓰는가」다.

    둘을 나눈 이유: 디스크에 이미 벡터 1,802개가 있다. 부르는 문만 닫으면 그 벡터로
    점수가 계속 달라지고(목록 85 · 상세 74), 캐시를 지워야만 숫자가 고정된다. 캐시를
    지우는 것은 담당자 결정이므로(§4-A-5), 읽지 않는 문을 따로 둔다.
    """
    from app.core.config import get_settings

    return bool(get_settings().semantic_fit)


@dataclass(frozen=True)
class SemanticFit:
    """의미 유사도 판정 결과.

    `fit_score` 가 None 이면 «재지 못했다»는 뜻이다. 0 과 구분한다.
    """

    fit_score: float | None
    label: FitLabel | None
    method: MatchMethod
    confidence: Literal["high", "medium", "low"]
    reason: str

    def to_dict(self) -> dict:
        return {
            "fit_score": self.fit_score,
            "label": self.label,
            "method": self.method,
            "confidence": self.confidence,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# 캐시 — 내용 해시 하나가 파일 하나
# ---------------------------------------------------------------------------


def _key(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:32]


def _cache_path(key: str) -> Path:
    # 파일이 한 폴더에 수천 개 쌓이지 않게 앞 두 글자로 나눈다.
    return CACHE_DIR / key[:2] / f"{key}.json"


@lru_cache(maxsize=512)
def _read_cache_file(key: str, cache_dir: str) -> tuple[float, ...] | None:
    """캐시 파일 한 개를 읽어 «프로세스 안»에 들고 있는다.

    목록 한 번에 공고 100건이 들어오는데 공고마다 회사 프로필 문구 24개를 함께 재므로,
    같은 문구 파일을 100번 다시 읽게 된다 (실측: 목록 1회 0.196초 → 1.228초, 같은 파일
    2,592회 재읽기). LRU 라서 매번 쓰이는 프로필 문구는 남고 공고는 밀려난다 —
    이 쓰임새에 정확히 맞는다.

    **합성 벡터는 돌려주지 않는다.** `store_cached(..., synthetic=True)` 로 들어간 시험용
    벡터가 실제 캐시에 섞이면, 운영이 그것을 진짜 임베딩으로 쓰고 화면에 「AI 의미 매칭」이라
    적는다. 잰 적 없는 값을 쟀다고 말하게 되므로 아예 못 읽게 막는다.
    """
    path = Path(cache_dir) / key[:2] / f"{key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("synthetic") and not ALLOW_SYNTHETIC_VECTORS:
        return None
    vector = payload.get("vector")
    return tuple(vector) if isinstance(vector, list) and vector else None


def load_cached(text: str) -> list[float] | None:
    # CACHE_DIR 도 키에 넣는다. 안 넣으면 시험이 캐시 폴더를 바꿔도 앞 시험의 벡터가 그대로
    # 나온다 (실제로 그랬다 — 키워드 경로 시험이 EMBEDDING 을 받았다).
    vector = _read_cache_file(_key(text), str(CACHE_DIR))
    return list(vector) if vector else None


def store_cached(text: str, vector: list[float], *, synthetic: bool = False) -> None:
    """벡터를 캐시에 넣는다.

    `synthetic=True` 는 **진짜 임베딩이 아니라 시험용 합성 벡터**라는 표시다. 이것이 없으면
    나중에 캐시를 보고 「이 점수가 실제 임베딩으로 나온 값인가」를 판별할 수 없다.
    """
    path = _cache_path(_key(text))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"vector": vector, "chars": len(text), "synthetic": synthetic}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    # 방금 쓴 것을 곧바로 읽어야 한다. 비우지 않으면 직전의 「없음」이 그대로 남는다.
    _read_cache_file.cache_clear()


def cache_fingerprint() -> str:
    """벡터 캐시의 **지문** — 파일 수와 가장 최근 수정 시각 (prompt_05 §4-B-1).

    이것이 왜 필요한가. 목록은 판정을 메모하고(회사·날짜·캐시 시각이 같으면 그대로 쓴다),
    상세는 그때그때 계산한다. 그래서 **메모를 쓴 뒤에 벡터가 생기면** 목록은 옛 입력으로
    낸 점수를, 상세는 새 입력으로 낸 점수를 말한다 — 재검증에서 목록 85 · 상세 74 였다.
    같은 함수를 쓰는 것으로는 부족하고 **같은 입력**이어야 한다(11차 ISSUE-097 의 다음 칸).

    지문을 메모 열쇠에 넣으면 벡터가 하나라도 늘 때 메모가 저절로 무효가 된다.

    꺼져 있으면 벡터를 읽지 않으므로 지문도 필요 없다 — 「off」 하나로 답한다. 1,802개를
    매 요청마다 세는 일도 함께 없어진다(꺼짐이 시연 기본값이다).
    """
    if not semantic_fit_enabled():
        return "off"
    count = 0
    latest = 0
    try:
        for path in CACHE_DIR.rglob("*.json"):
            try:
                latest = max(latest, path.stat().st_mtime_ns)
            except OSError:  # 세는 중에 사라진 파일 — 지문이 조금 틀려도 무효화는 안전한 쪽이다
                continue
            count += 1
    except OSError:
        return "unreadable"
    return f"{count}-{latest}"


def embed_cached(texts: list[str]) -> dict[str, list[float]] | None:
    """캐시를 먼저 보고, 없는 것만 한 번에 부른다. 부를 수 없으면 None.

    None 은 「임베딩을 쓸 수 없다」이며 호출자는 키워드 경로로 간다.
    """
    unique = [t for t in dict.fromkeys(t.strip() for t in texts if t and t.strip())]
    if not unique:
        return {}

    result: dict[str, list[float]] = {}
    missing: list[str] = []
    for text in unique:
        cached = load_cached(text)
        if cached is not None:
            result[text] = cached
        else:
            missing.append(text)

    if not missing:
        return result

    if not llm_client.embedding_available():
        # 캐시에 있는 것만으로는 판정하지 않는다 — 일부만 재면 순서가 뒤틀린다.
        return None
    try:
        vectors = llm_client.embed(missing)
    except Exception as exc:  # noqa: BLE001 — 키 거부·한도·네트워크 전부 같은 결말이다
        logger.info("의미 매칭 임베딩 실패: %s", llm_client.embed_failure_reason(exc))
        return None
    for text, vector in zip(missing, vectors, strict=True):
        store_cached(text, vector)
        result[text] = vector
    llm_client.note_embedding_success()
    return result


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _normalize(raw: float) -> float:
    """코사인 원값을 0~1 로 편다. 왜 필요한지는 모듈 주석의 `_COSINE_FLOOR` 참고."""
    if _COSINE_CEIL <= _COSINE_FLOOR:
        return max(0.0, min(1.0, raw))
    scaled = (raw - _COSINE_FLOOR) / (_COSINE_CEIL - _COSINE_FLOOR)
    return max(0.0, min(1.0, scaled))


def label_of(score: float) -> FitLabel:
    if score >= HIGH_THRESHOLD:
        return "높음"
    if score >= MID_THRESHOLD:
        return "보통"
    return "낮음"


_SPLIT = re.compile(r"[·,/|]|\s{2,}")


def profile_phrases(
    *,
    business_domains: list[str] | tuple[str, ...] = (),
    target_clients: list[str] | tuple[str, ...] = (),
    certifications: list[str] | tuple[str, ...] = (),
) -> list[str]:
    """회사 프로필을 «문구 단위»로 쪼갠다.

    프로필 전체를 한 덩어리로 임베딩하면 사유를 만들 수 없다 — 「무엇과 가까운가」를
    말하려면 비교 대상이 문구여야 한다. 활동 지역은 넣지 않는다: 지역은 의미가 아니라
    자격 조건이고, 규칙 판정(`_strategic_fit`)이 따로 본다.
    """
    phrases: list[str] = []
    for group, prefix in ((business_domains, ""), (target_clients, "주요 고객: "), (certifications, "보유 인증: ")):
        for value in group:
            for piece in _SPLIT.split(str(value or "")):
                piece = piece.strip()
                if len(piece) >= 2:
                    text = f"{prefix}{piece}"
                    if text not in phrases:
                        phrases.append(text)
    return phrases


def notice_text(*, title: str, summary: str | None = None, task: str | None = None) -> str:
    """공고 한 건을 의미 비교용 한 덩어리로.

    제목만으로는 「AI 교육」과 「AI 개발」이 거의 붙어 버린다. 과업 내용이 있으면 함께 넣되,
    너무 길면 앞부분만 쓴다 — 임베딩은 길수록 흐려진다.
    """
    parts = [title.strip()]
    for extra in (summary, task):
        if extra and extra.strip():
            parts.append(extra.strip()[:600])
    return " ".join(parts)


def match(
    *,
    notice: str,
    phrases: list[str],
    keyword_reason: str = (
        "AI 의미 매칭을 쓸 수 없어(키 없음 · 사용량 소진 등) 낱말 기준으로만 판정했습니다."
    ),
) -> SemanticFit:
    """공고 한 건과 회사 프로필 문구들의 의미 유사도.

    임베딩을 못 쓰면 `method="KEYWORD"` · `fit_score=None` 이다 — 호출자는 기존 규칙 값을
    그대로 쓰면 된다.

    **스위치가 꺼져 있으면 캐시 벡터가 있어도 재지 않는다** (§4-A-1). 막는 자리를 여기
    하나로 둔 이유는 `complete_structured` 와 같다 — 호출자는 `bizinfo_service.support_fit`
    과 `recommendation.semantic_fit` 둘이고 앞으로 더 늘 수 있다. 각자 스위치를 보게 하면
    새로 생기는 경로가 반드시 하나 빠진다.
    """
    if not semantic_fit_enabled():
        return SemanticFit(None, None, "KEYWORD", "low", SEMANTIC_OFF_REASON)
    if not phrases:
        return SemanticFit(None, None, "KEYWORD", "low", "회사 프로필에 사업영역이 없어 AI 의미 매칭을 하지 않았습니다.")
    if len(notice.strip()) < MIN_TEXT_CHARS:
        return SemanticFit(None, None, "KEYWORD", "low", "공고 본문이 짧아 AI 의미 매칭을 하지 않았습니다.")

    vectors = embed_cached([notice, *phrases])
    if vectors is None:
        return SemanticFit(None, None, "KEYWORD", "low", keyword_reason)

    notice_vector = vectors.get(notice.strip())
    if not notice_vector:
        return SemanticFit(None, None, "KEYWORD", "low", keyword_reason)

    best_phrase = ""
    best_raw = -1.0
    for phrase in phrases:
        vector = vectors.get(phrase.strip())
        if not vector:
            continue
        raw = cosine(notice_vector, vector)
        if raw > best_raw:
            best_raw, best_phrase = raw, phrase
    if best_raw < 0:
        return SemanticFit(None, None, "KEYWORD", "low", keyword_reason)

    score = round(_normalize(best_raw), 4)
    label = label_of(score)
    # 원값이 바닥·천장에 붙으면 「그 구간 밖」이라 눈금이 의미를 잃는다. 그때는 확신을 낮춘다.
    confidence = "high" if _COSINE_FLOOR + 0.03 < best_raw < _COSINE_CEIL - 0.03 else "medium"
    return SemanticFit(
        fit_score=score,
        label=label,
        method="EMBEDDING",
        confidence=confidence,
        reason=f"회사 사업영역 「{best_phrase}」와 가장 가깝습니다 (유사도 {best_raw:.2f}).",
    )
