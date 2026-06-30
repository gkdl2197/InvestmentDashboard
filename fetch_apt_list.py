import requests
import time
import os
from dotenv import load_dotenv

load_dotenv()

SERVICE_KEY = "ed5eb4cbab5b22ea97fe39d5fbb5c3b0b27037c3bc5c1d43ed3e2f7e37d261ba"
BASE_URL = "https://apis.data.go.kr/1613000/AptListService3/getTotalAptList3"

def fetch_page(page_no, num_of_rows=1000):
    params = {
        "serviceKey": SERVICE_KEY,
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "_type": "json"
    }
    res = requests.get(BASE_URL, params=params, timeout=15)
    res.raise_for_status()
    return res.json()

def parse_json(data):
    body = data.get("response", {}).get("body", {})
    raw_items = body.get("items", [])

    # items가 단일 객체로 올 수도 있어 리스트로 강제 변환
    if isinstance(raw_items, dict):
        raw_items = [raw_items]

    items = []
    for item in raw_items:
        kapt_code = (item.get("kaptCode") or "").strip()
        kapt_name = (item.get("kaptName") or "").strip()
        as1 = (item.get("as1") or "").strip()
        as2 = (item.get("as2") or "").strip()
        as3 = (item.get("as3") or "").strip()
        as4 = (item.get("as4") or "").strip() if item.get("as4") else ""

        if kapt_code and kapt_name:
            items.append({
                "complex_code": kapt_code,
                "complex_name": kapt_name,
                "sido": as1,
                "sigungu": as2,
                "dong": (as3 + " " + as4).strip(),
                "road_address": f"{as1} {as2} {as3} {as4}".strip()
            })

    total_count = body.get("totalCount", 0)
    return items, int(total_count)

def fetch_all_apartments():
    all_items = []
    num_of_rows = 1000

    data = fetch_page(1, num_of_rows)
    items, total_count = parse_json(data)
    all_items.extend(items)

    total_pages = (total_count // num_of_rows) + 1
    print(f"총 {total_count}건 / 총 {total_pages}페이지")
    print(f"[1/{total_pages}] {len(items)}건 수집")

    for page in range(2, total_pages + 1):
        try:
            data = fetch_page(page, num_of_rows)
            items, _ = parse_json(data)
            all_items.extend(items)
            print(f"[{page}/{total_pages}] {len(items)}건 수집 (누적 {len(all_items)}건)")
            time.sleep(0.3)
        except Exception as e:
            print(f"❌ 페이지 {page} 실패: {e}")
            time.sleep(2)

    return all_items

if __name__ == "__main__":
    apartments = fetch_all_apartments()
    print(f"\n✅ 총 {len(apartments)}건 수집 완료\n")

    if len(apartments) == 0:
        print("⚠️ 수집된 데이터가 없습니다.")
        exit()

    print("샘플 데이터:", apartments[0])

    from supabase import create_client
    SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    batch_size = 500
    for i in range(0, len(apartments), batch_size):
        batch = apartments[i:i+batch_size]
        try:
            supabase.table("real_estate_complexes").upsert(batch, on_conflict="complex_code").execute()
            print(f"DB 업로드 {min(i+batch_size, len(apartments))}/{len(apartments)}")
        except Exception as e:
            print(f"❌ 업로드 실패 (batch {i}): {e}")