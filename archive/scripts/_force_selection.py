"""시장 필터를 우회하고 종목 채점만 진행 (테스트 전용).

실제 매수에는 사용 금지. KOSPI 약세장 등 시장 필터에 막혔을 때
'그래도 어떤 종목이 점수 높은지' 확인용.

사용:
  python scripts/_force_selection.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts import direct_closing_bet as dcb


# Monkey-patch: 시장 필터 / 레짐 / 미국 게이트 모두 통과
def _fake_market_filter(*args, **kwargs):
    return {"ok": True, "reason": "[FORCE] 시장 필터 우회"}


def _fake_classify_regime(*args, **kwargs):
    return "neutral"  # weak이 아닌 값


def _fake_us_overnight():
    return 0.0, 0.0  # 차단되지 않는 값


dcb.evaluate_market_filter = _fake_market_filter
dcb.classify_regime = _fake_classify_regime
dcb.get_overnight_us_change = _fake_us_overnight


async def main():
    print("=" * 70)
    print("[FORCE] 시장 필터 우회 — 종목 채점만 진행 (매수 없음)")
    print("=" * 70)
    candidates = await dcb.phase_selection()

    print("\n" + "=" * 70)
    if candidates:
        print(f"후보 {len(candidates)}종목 (MIN_SCORE {dcb.MIN_SCORE} 이상)")
        print("-" * 70)
        for i, c in enumerate(candidates, 1):
            qty = dcb.calc_position_qty(c["composite"], c["current_price"])
            cat = "📰" if c.get("has_catalyst") else "—"
            print(
                f"{i}. {c['company_name']:<14}({c['symbol']}) [{c.get('sector', '?'):<6}] {cat}"
            )
            print(
                f"   점수 {c['composite']:5.1f}  가 {c['current_price']:>9,.0f}원  수량 {qty}주"
            )
    else:
        print("후보 0종목 — 필터 통과했어도 MIN_SCORE 미달")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
