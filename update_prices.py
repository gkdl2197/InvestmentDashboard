import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

SERVICE_KEY = "ed5eb4cbab5b22ea97fe39d5fbb5c3b0b27037c3bc5c1d43ed3e2f7e37d261ba"
BASE_URL = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

def get_recent_price(bjd_code, apt_name, area=None):
    lawd_cd = bjd_code[:5] if bjd_code and len(bjd_code) >= 5 else None
    if not lawd_cd:
        return None

    now = datetime.now()
    months_to_try = [
        (now - timedelta(days=30 * i)).strftime("%Y%m")
        for i in range(0, 4)
    ]

    for deal_ymd in months_to_try:
        try:
            params = {
                "serviceKey": SERVICE_KEY,
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": deal_ymd,
                "pageNo": 1,
                "numOfRows": 100,
                "_type": "json"
            }
            res = requests.get(BASE_URL, params=params, timeout=10)
            if res.status_code != 200:
                continue

            body = res.json().get("response", {}).get("body", {})
            items = body.get("items", {})
            if not items or items == "":
                continue

            item_list = items.get("item", [])
            if isinstance(item_list, dict):
                item_list = [item_list]
            if not item_list:
                continue

            clean_name = apt_name.replace(" ", "")
            matched = []
            for item in item_list:
                item_apt = str(item.get("aptNm", "")).replace(" ", "")
                if clean_name in item_apt or item_apt in clean_name:
                    try:
                        # ✅ 면적 필터링 추가
                        if area and area > 0:
                            item_area = float(str(item.get("excluUseAr", "0")).replace(",", "") or 0)
                            if abs(item_area - area) > 3:  # 3㎡ 오차 허용
                                continue

                        price = int(str(item.get("dealAmount", "0")).replace(",", "")) * 10000
                        year = str(item.get("dealYear", ""))
                        month = str(item.get("dealMonth", "")).zfill(2)
                        day = str(item.get("dealDay", "")).zfill(2)
                        matched.append({"price": price, "date": f"{year}{month}{day}"})
                    except:
                        continue

            if matched:
                matched.sort(key=lambda x: x["date"], reverse=True)
                print(f"✅ {apt_name} → {deal_ymd} 실거래가: {matched[0]['price']:,}원")
                return matched[0]["price"]

        except Exception as e:
            print(f"❌ {apt_name} {deal_ymd}: {e}")
            continue

    print(f"⚠️ {apt_name}: 최근 4개월 내 거래 없음")
    return None

if __name__ == "__main__":
    from supabase import create_client
    SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 관심부동산 목록 조회
    res = supabase.table("real_estate_portfolio")\
        .select("id, name, bjd_code, area")\
        .eq("is_watchlist", True)\
        .execute()

    watch_list = res.data or []
    print(f"관심부동산 {len(watch_list)}건 시세 업데이트 시작")

    for item in watch_list:
        bjd_code = item.get("bjd_code", "")
        name = item.get("name", "")
        if not bjd_code:
            print(f"⚠️ {name}: bjd_code 없음 스킵")
            continue

        price = get_recent_price(bjd_code, name, area=item.get("area") or 0)
        if price:
            supabase.table("real_estate_portfolio")\
                .update({"current_price": price})\
                .eq("id", item.get("id"))\
                .execute()
            print(f"💾 {name} → DB 업데이트 완료: {price:,}원")

    print("\n✅ 전체 시세 업데이트 완료")