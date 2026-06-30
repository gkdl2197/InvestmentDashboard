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
    if isinstance(raw_items, dict):
        raw_items = [raw_items]

    items = []
    for item in raw_items:
        kapt_code = (item.get("kaptCode") or "").strip()
        bjd_code = (item.get("bjdCode") or "").strip()
        if kapt_code:
            items.append({
                "complex_code": kapt_code,
                "bjd_code": bjd_code
            })

    total_count = body.get("totalCount", 0)
    return items, int(total_count)

def fetch_all_bjd_codes():
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
    items = fetch_all_bjd_codes()
    print(f"\n✅ 총 {len(items)}건 수집 완료\n")

    if not items:
        print("⚠️ 수집된 데이터가 없습니다.")
        exit()

    from supabase import create_client
    SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # upsert로 bjd_code만 갱신 (complex_code가 같으면 UPDATE처럼 동작)
    # 단, upsert는 NOT NULL 필드(complex_name)가 없으면 실패하므로 개별 update 방식 사용
    success, fail = 0, 0
    for i, item in enumerate(items):
        try:
            supabase.table("real_estate_complexes")\
                .update({"bjd_code": item["bjd_code"]})\
                .eq("complex_code", item["complex_code"])\
                .execute()
            success += 1
        except Exception as e:
            fail += 1
        if (i + 1) % 500 == 0:
            print(f"진행 {i+1}/{len(items)} (성공 {success}, 실패 {fail})")

    print(f"\n✅ 최종 완료 — 성공 {success}건, 실패 {fail}건")